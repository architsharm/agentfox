#!/usr/bin/env bash
# Tell Bing (and Yandex, Seznam, Naver) about every URL in the live sitemap via IndexNow.
# Google does not use IndexNow; it reads the sitemap submitted in Search Console.
#
#   scripts/ops/indexnow.sh                 # after a deploy that adds or changes pages
#
# The key must be served at https://useagentfox.com/<key>.txt, which
# dashboard/public/<key>.txt does once deployed. Rotating it means renaming that file
# and changing KEY here.
set -euo pipefail

HOST="${SITE_HOST:-useagentfox.com}"
KEY="d575528c9753148dc8dec098f612b55c"

curl -fsS "https://$HOST/$KEY.txt" | grep -qx "$KEY" || { echo "key file not live at https://$HOST/$KEY.txt" >&2; exit 1; }

urls=$(curl -fsS "https://$HOST/sitemap.xml" | grep -o '<loc>[^<]*' | sed 's/<loc>//')
[ -n "$urls" ] || { echo "no URLs in sitemap" >&2; exit 1; }

body=$(printf '%s\n' "$urls" | python3 -c '
import json, sys
host, key = sys.argv[1], sys.argv[2]
print(json.dumps({"host": host, "key": key, "keyLocation": f"https://{host}/{key}.txt",
                  "urlList": [u.strip() for u in sys.stdin if u.strip()]}))' "$HOST" "$KEY")

code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST https://api.indexnow.org/indexnow \
  -H 'Content-Type: application/json; charset=utf-8' -d "$body")
echo "IndexNow: $(printf '%s\n' "$urls" | wc -l | tr -d ' ') URLs, HTTP $code (200/202 = accepted)"
[ "$code" = 200 ] || [ "$code" = 202 ]
