#!/usr/bin/env bash
# Generate a self-signed TLS certificate for HTTPS access.
#
# Usage:
#   scripts/generate_cert.sh [IP ...]
#
# Without arguments it auto-detects all non-loopback IPv4 addresses and writes
# ./cert.pem and ./key.pem (valid 10 years). Start the server afterwards with:
#   SSL_CERT_FILE=$PWD/cert.pem SSL_KEY_FILE=$PWD/key.pem python3 -m py_remote_input
set -euo pipefail

out_dir="${OUT_DIR:-$PWD}"
cert="$out_dir/cert.pem"
key="$out_dir/key.pem"

if [ "$#" -gt 0 ]; then
  ips=("$@")
else
  mapfile -t ips < <(ip -4 -o addr show scope global 2>/dev/null | awk '{split($4, a, "/"); print a[1]}')
fi

if [ "${#ips[@]}" -eq 0 ]; then
  echo "No LAN IPv4 address found; pass one explicitly: $0 192.168.x.x" >&2
  exit 1
fi

alt="subjectAltName="
first=1
for ip in "${ips[@]}"; do
  [ "$first" -eq 1 ] || alt+=","
  alt+="IP:$ip"
  first=0
done

echo "Generating certificate for: ${ips[*]}"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$key" -out "$cert" -days 3650 \
  -subj "/CN=remote-input" \
  -addext "$alt"
chmod 600 "$key"

echo
echo "Wrote $cert and $key"
echo "Start with:"
echo "  SSL_CERT_FILE=$cert SSL_KEY_FILE=$key python3 -m py_remote_input"
