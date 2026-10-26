#!/usr/bin/env bash
# Yatta: build an avatar from <avatar-dir>/sources.json and train one GaussianTalker model per speech feature
# listed in <avatar-dir>/avatar.json ("features"), skipping completed steps on rerun. Yatta launches it as the
# systemd user unit yatta-train-<id>; progress is read from <avatar-dir>/pipeline.log.
# Markers: runs/<feature>/done per trained variant, <avatar-dir>/done when all finish, <avatar-dir>/failed on error.
# Needs GAUSSIAN_TALKER_ROOT (research repository with the environments and scripts) and YATTA_PYTHON + PYTHONPATH
# (to query Yatta's GPU gate); Yatta sets all three.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${GAUSSIAN_TALKER_ROOT:?set GAUSSIAN_TALKER_ROOT}"; cd "$ROOT"
A="$(readlink -f "${1:?avatar dir}")"; H=$A/data/identity
PY=$ROOT/.venv/bin/python; DS=$ROOT/.local/envs/deepspeech/bin/python; SF=$ROOT/.local/envs/speechfeat/bin/python
SPY="${YATTA_PYTHON:-python3}"; POLL="${YATTA_GPU_POLL:-1800}"; MIN_FREE_GB="${YATTA_MIN_FREE_GB:-15}"
CONFIGS="${YATTA_TRAINING_CONFIGS:-$HERE/configs}"  # a directory of <feature>.py configs; tests point it at short runs
log() { echo "$(date -Is) $*"; }
fail() { log "FAILED: $*"; echo "$*" > $A/failed; exit 1; }
gpu_wait() {  # other projects' GPU jobs block; this project's own renders do not (Henry, 2026-10-20: never share)
  # Idle must hold across two checks 2 min apart: some projects run back-to-back short processes, and a long
  # training started in a gap between them would then compete with the next one for hours.
  local busy
  while :; do
    busy="$($SPY -m yatta.engines gpu-foreign 2>/dev/null)"
    if [ -z "$busy" ]; then sleep 120; busy="$($SPY -m yatta.engines gpu-foreign 2>/dev/null)"; [ -z "$busy" ] && return; fi
    log "waiting for GPU: $(echo "$busy" | head -1 | cut -d' ' -f2-)"; sleep $POLL
  done; }
mapfile -t FEATURES < <(python3 -c "import json,sys; print('\n'.join(json.load(open(sys.argv[1]))['features']))" $A/avatar.json)
rm -f $A/failed

if [ ! -f $H/preparation.json ]; then
  [ -d $H ] && fail "$H exists without preparation.json (interrupted prepare); move it aside and retry"
  free=$(df -BG --output=avail $A | tail -1 | tr -dc 0-9)
  [ "$free" -ge "$MIN_FREE_GB" ] || fail "only ${free} GB free on the data disk; training needs ${MIN_FREE_GB} GB"
  log "prepare"; mkdir -p $A/data; python3 $HERE/prepare_sources.py --sources $A/sources.json --output $H < /dev/null || fail prepare
fi
N=$(ls $H/ori_imgs/*.jpg | wc -l); log "frames: $N"
T=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $H/aud.wav)
SPLIT=$(python3 -c "print($T*10/11)"); NOVEL=$(python3 -c "print($T/11)")
[ -f $H/aud_novel.wav ] || {
  ffmpeg -nostdin -v error -i $H/aud.wav -f wav -ar 16000 -t $SPLIT $H/aud_train.wav &&
  ffmpeg -nostdin -v error -i $H/aud.wav -f wav -ar 16000 -ss $SPLIT -t $NOVEL $H/aud_novel.wav; } || fail "audio split"
[ -f $H/aud_ds.npy ] || { log "speech features: deepspeech"; $DS scripts/extract_deepspeech.py --wav $H/aud.wav --output $H/aud.npy < /dev/null && cp $H/aud.npy $H/aud_ds.npy; } || fail deepspeech
[ -f $H/au.csv ] || { log "blink detection (OpenFace)"; scripts/extract_au45.sh $H/video.mp4 < /dev/null; } || fail "blink detection"
if [ ! -f $H/logs/task7_landmarks.json ] || ! grep -q '"exit_code": 0' $H/logs/task7_*.json; then
  gpu_wait; log "face parsing and landmarks"; $PY scripts/preprocess.py $H/video.mp4 --stages 4 5 7 < /dev/null || fail "face parsing"
fi
if [ ! -f $H/bc_upstream.jpg ]; then
  # One backdrop: the median over the first recording (recordings may come from different rooms).
  mv $H/bc.jpg $H/bc_upstream.jpg; log "background"
  EXCL=$(python3 -c "import json,sys; s=json.load(open(sys.argv[1]))['segments']; print(' '.join(str(i) for i in range(s[1]['first_frame'], $N)) if len(s) > 1 else '')" $H/preparation.json)
  $PY scripts/estimate_background.py --data $H --output $H/bc.jpg ${EXCL:+--exclude $EXCL} < /dev/null || fail background
fi
if [ ! -f $H/logs/task6_torso.json ] || ! grep -q '"exit_code": 0' $H/logs/task6_*.json; then
  log "torso"; $PY scripts/preprocess.py $H/video.mp4 --stages 6 < /dev/null || fail torso
fi
if [ ! -f $H/transforms_val.json ]; then
  gpu_wait; log "face tracking"; $PY scripts/preprocess.py $H/video.mp4 --stages 8 9 < /dev/null || fail "face tracking"
fi
log "validate"; $PY scripts/reproduce.py validate --data $H > $A/validate.json < /dev/null || fail validate
[ -f $A/tracking.json ] || $PY scripts/check_tracking.py --data $H --samples 0 $((N/4)) $((N/2)) $((3*N/4)) $((N-1)) \
  --report $A/tracking.json < /dev/null || fail "tracking check"

for f in "${FEATURES[@]}"; do
  R=$A/runs/$f; [ -f $R/done ] && { log "$f already trained"; continue; }
  if [ $f = deepspeech ]; then D=$H; else
    D=$A/data/$f; mkdir -p $D
    for e in $H/*; do n=$(basename $e); case $n in aud_ds.npy|aud.npy) ;; *) [ -e $D/$n ] || ln -s $e $D/$n;; esac; done
    [ -f $D/aud_ds.npy ] || { log "speech features: $f"; $SF scripts/extract_speech_features.py --model $f --wav $H/aud.wav --output $D/aud_ds.npy < /dev/null; } || fail "$f features"
  fi
  mkdir -p $R; cp $ROOT/upstream.lock.json $R/ 2>/dev/null
  gpu_wait; log "training $f"
  $ROOT/scripts/train_resilient.sh $R $D $CONFIGS/$f.py 20 500 > $R/supervisor.log 2>&1 < /dev/null
  ITER=$(python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location('c',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.OptimizationParams['iterations'])" $R/config.py)
  [ -f $R/model/point_cloud/iteration_$ITER/point_cloud.ply ] || fail "$f training did not finish (see $R/supervisor.log)"
  gpu_wait; log "preview $f"
  OMP_NUM_THREADS=1 PYTHONUNBUFFERED=1 $PY scripts/reproduce.py render --data $D --config $R/config.py --model $R/model \
    --iteration $ITER --batch 8 --report $R/render.json > $R/render.log 2>&1 < /dev/null || fail "$f preview render (see $R/render.log)"
  V=$R/model/test/ours_$ITER/renders/${f}_test_${ITER}iter_renders.mov
  $PY scripts/evaluate_render.py --data $D --video $V --report $R/eval.json > $R/evaluate.log 2>&1 < /dev/null || log "$f evaluation failed (see $R/evaluate.log)"
  ffmpeg -nostdin -v error -y -i $V -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -movflags +faststart $R/preview.mp4 || fail "$f preview mp4"
  # Resume checkpoints are only for interrupted training; the final model stays in point_cloud/.
  rm -f $R/model/chkpnt_*.pth
  touch $R/done; log "$f ready"
done
log "done"; echo ok > $A/done
