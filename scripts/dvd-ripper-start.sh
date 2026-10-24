#!/bin/bash
# (Re)create the dvd-ripper container. The drive's /dev/sgN number can change
# between reboots, so look it up instead of hardcoding it.
set -e
SG=$(basename "$(ls -d /sys/class/block/sr0/device/scsi_generic/sg* | head -1)")
echo "DVD drive: /dev/sr0 + /dev/$SG"
docker rm -f dvd-ripper 2>/dev/null || true
docker run -d --name dvd-ripper --restart no -p 5800:5800 \
  --device /dev/sr0 --device "/dev/$SG" \
  -e USER_ID=1000 -e GROUP_ID=1000 \
  -e AUTO_DISC_RIPPER=1 -e AUTO_DISC_RIPPER_EJECT=1 \
  -v /home/kadin/dvd-ripper-config:/config \
  -v /mnt/nvme/homelab2/shared/media/_rips:/output \
  jlesage/makemkv:latest
