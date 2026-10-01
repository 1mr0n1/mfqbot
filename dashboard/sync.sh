#!/bin/sh
# The dashboard page lives in backend/admin.html; this folder is the copy that gets deployed to Vercel.
cd "$(dirname "$0")/.." && cp backend/admin.html dashboard/index.html && echo "dashboard/index.html updated"
