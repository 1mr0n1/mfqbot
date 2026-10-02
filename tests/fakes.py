"""A stand-in for Telegram that records everything the account does, for the full project check."""
from datetime import datetime, timezone
from types import SimpleNamespace as NS

from telethon.tl.types import Channel, User

from userbot import simulate as SIM


def user(i, first, last=None, username=None, contact=True):
    return User(id=i, first_name=first, last_name=last, username=username, contact=contact)


def peer(e):
    return e.id if isinstance(e, User) else int(f"-100{e.id}")


class Client(SIM.FakeClient):
    """SIM.FakeClient (histories, sent messages) + dialogs, entities, and a log of every Telegram request made."""

    def __init__(self, me, people=(), groups=()):
        super().__init__()
        self.me, self.people, self.groups = me, list(people), list(groups)
        self.calls: list[str] = []      # "RequestName(args)" / "method(args)"
        self.saved: list = []           # what went to Saved Messages (texts and files)
        self.unread: dict[int, int] = {}

    async def get_me(self):
        return self.me

    def everyone(self):
        return self.people + self.groups

    async def get_entity(self, ref):
        if ref in ("me", self.me.id):
            return self.me
        for e in self.everyone():
            name = (getattr(e, "username", None) or "").lower()
            if ref in (e.id, peer(e)) or (isinstance(ref, str) and name and ref.lstrip("@").lower() == name):
                return e
        raise ValueError(f"no entity {ref!r}")

    async def get_input_entity(self, e):
        return e if not isinstance(e, int) else await self.get_entity(e)

    async def get_dialogs(self, limit=0):
        return [NS(id=peer(e), name=(e.first_name + (" " + e.last_name if e.last_name else "")) if isinstance(e, User) else e.title,
                   entity=e, unread_count=self.unread.get(peer(e), 0), is_group=isinstance(e, Channel) and e.megagroup,
                   message=(self.histories.get(peer(e)) or [None])[0], unread_mentions_count=0) for e in self.everyone()]

    async def iter_dialogs_list(self, limit=0):
        return await self.get_dialogs(limit)

    def iter_dialogs(self, limit=0):
        client = self

        class It:
            def __aiter__(s):
                s.items = None
                return s

            async def __anext__(s):
                if s.items is None:
                    s.items = iter(await client.get_dialogs(limit))
                try:
                    return next(s.items)
                except StopIteration:
                    raise StopAsyncIteration
        return It()

    def _key(self, chat):
        if chat == "me" or chat is self.me:
            return "me"
        return chat if isinstance(chat, int) else peer(chat)

    async def get_messages(self, chat, limit=30, ids=None, search=None, min_id=0, **kw):
        key = self._key(chat) if chat is not None else None
        if ids is not None:
            return next((m for m in self.saved if getattr(m, "id", None) == ids), None)
        if chat is None:
            found = [m for h in self.histories.values() for m in h if search and search.lower() in (m.raw_text or "").lower()]
            return found[:limit]
        items = [m for m in self.histories.get(key, []) if m.id > min_id and (not search or search.lower() in (m.raw_text or "").lower())]
        out = items[:limit] if limit else NS(total=len(items))
        return out

    async def send_message(self, chat, text="", reply_to=None, schedule=None, file=None, **kw):
        key = self._key(chat)
        self.calls.append(f"send_message({key}, {text!r}" + (", scheduled" if schedule else "") + (", poll" if file is not None else "") + ")")
        if key == "me":
            msg = SIM.make(text, out=True)
            self.saved.append(msg)
            sink = SIM._emit_sink.get()
            if sink is not None:
                sink.append(("note", text))
            return msg
        return self._record(key, ("↩ " if reply_to else "") + (text or "[poll]"))

    async def send_file(self, chat, file, voice_note=False, video_note=False, **kw):
        key = self._key(chat)
        self.calls.append(f"send_file({key}, voice={voice_note}, video={video_note})")
        msg = SIM.make("", out=True, media=file, voice=voice_note or None, video_note=video_note or None)
        if key == "me":
            self.saved.append(msg)
            return msg
        self.sent.setdefault(key, []).append("[file]")
        self.histories.setdefault(key, []).insert(0, msg)
        return msg

    async def send_read_acknowledge(self, chat):
        self.calls.append(f"send_read_acknowledge({self._key(chat)})")

    async def upload_file(self, data, file_name=None):
        self.calls.append(f"upload_file({file_name})")
        return NS(name=file_name)

    async def forward_messages(self, entity, messages, **kw):
        self.calls.append(f"forward_messages({self._key(entity)})")
        self.sent.setdefault(self._key(entity), []).append("[forwarded]")

    async def delete_messages(self, entity, ids, revoke=True):
        self.calls.append(f"delete_messages({self._key(entity)}, {len(ids)})")

    async def edit_message(self, entity, msg_id, text):
        self.calls.append(f"edit_message({self._key(entity)}, {text!r})")

    async def get_profile_photos(self, who, limit=1):
        from telethon.tl.types import Photo
        return [Photo(id=900 + i, access_hash=1, file_reference=b"x", date=datetime.now(timezone.utc), sizes=[], dc_id=1)
                for i in range(limit)]

    async def __call__(self, request):
        name = type(request).__name__
        self.calls.append(name)
        reaction = getattr(request, "reaction", None)
        if reaction:
            self.sent.setdefault(self._key(request.peer), []).append(f"[reaction {reaction[0].emoticon}]")
        if name == "GetPeerDialogsRequest":
            return NS(dialogs=[NS(read_outbox_max_id=10 ** 9)])
        return NS(full_user=NS(about="bio text", blocked=False), stickers=[], set=NS(title="pack", short_name="pack"))

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        async def method(*a, **k):
            self.calls.append(f"{name}({', '.join(str(self._key(x)) if isinstance(x, (User, Channel, int)) else type(x).__name__ for x in a)})")
            return NS(id=1)
        return method


class Event:
    """What a Telethon NewMessage event looks like to the handlers."""

    def __init__(self, client, text, chat_id, out=False, sender=None, reply_to=None, group=False, mentioned=False, **kw):
        self.message = SIM.make(text, out=out, mentioned=mentioned, sender=sender, **kw)
        self.message.chat_id = chat_id
        self.raw_text, self.chat_id, self.id = text, chat_id, self.message.id
        self.is_private, self.is_group, self.is_reply = not group, group, reply_to is not None
        self.sender_id = getattr(sender, "id", None)
        self.date = datetime.now(timezone.utc)
        self.mentioned = mentioned
        self.pattern_match = None
        self.deleted = False
        self._reply, self._client, self._sender = reply_to, client, sender
        client.histories.setdefault(chat_id, []).insert(0, self.message)

        async def get_sender():
            return sender
        self.message.get_sender = get_sender

        async def get_chat():
            return await client.get_entity(chat_id)
        self.message.get_chat = get_chat

    async def delete(self):
        self.deleted = True

    async def get_reply_message(self):
        return self._reply

    async def get_sender(self):
        return self._sender

    async def get_chat(self):
        return await self._client.get_entity(self.chat_id)
