#!/usr/bin/env bash
# Create a fresh access key for the deepdoc-dispatch IAM user and write it to a
# 0600 file (never printed). Deletes the user's older keys so at most one is live.
# Usage: ./dispatch-key.sh /path/to/outfile.env
set -euo pipefail
OUT="${1:?usage: dispatch-key.sh /path/to/outfile.env}"
USER_NAME="deepdoc-dispatch"
for old in $(aws iam list-access-keys --user-name "$USER_NAME" --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
  aws iam delete-access-key --user-name "$USER_NAME" --access-key-id "$old"
done
umask 177
aws iam create-access-key --user-name "$USER_NAME" \
  --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text \
  | awk '{printf "AWS_ACCESS_KEY_ID=%s\nAWS_SECRET_ACCESS_KEY=%s\n",$1,$2}' > "$OUT"
echo "wrote key to $OUT (mode 600)"
