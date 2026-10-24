#!/bin/bash
# Move a finished DVD rip into the Jellyfin movies library.
# Usage: scripts/dvd-save-movie.sh "Bee Movie (2007)"
# Takes the newest folder in _rips, keeps its largest .mkv (the movie),
# and deletes the rest of that folder (trailers and extras).
set -e
NAME="$1"
[ -n "$NAME" ] || { echo 'Usage: dvd-save-movie.sh "Movie Title (Year)"'; exit 1; }

RIPS=/mnt/nvme/homelab2/shared/media/_rips
MOVIES=/mnt/nvme/homelab2/shared/media/movies

DIR=$(ls -td "$RIPS"/*/ 2>/dev/null | head -1)
[ -n "$DIR" ] || { echo "Nothing in $RIPS"; exit 1; }
MKV=$(ls -S "$DIR"*.mkv 2>/dev/null | head -1)
[ -n "$MKV" ] || { echo "No .mkv files in $DIR"; exit 1; }
[ ! -e "$MOVIES/$NAME" ] || { echo "$MOVIES/$NAME already exists"; exit 1; }

echo "Rip folder: $DIR"
echo "Movie file: $(basename "$MKV") ($(du -h "$MKV" | cut -f1))"
echo "Save as:    $MOVIES/$NAME/$NAME.mkv"
echo "The rest of the rip folder will be deleted."
read -rp "OK? [y/N] " ok
[ "$ok" = y ] || { echo "Cancelled."; exit 1; }

mkdir -p "$MOVIES/$NAME"
mv "$MKV" "$MOVIES/$NAME/$NAME.mkv"
rm -rf "$DIR"
echo "Done. Jellyfin will pick it up on its next scan."
