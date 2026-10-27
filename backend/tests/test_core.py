import json
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from yatta import core  # noqa: E402


def write_npy(path, shape):
    header = ("{'descr': '<f4', 'fortran_order': False, 'shape': (%s), }" % ", ".join(map(str, shape)) +
              ("," if len(shape) == 1 else "")).encode("latin1")
    header += b" " * (63 - (len(header) + 10) % 64) + b"\n"
    path.write_bytes(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header)


class StudioCoreTests(unittest.TestCase):
    def test_pingpong_loops_without_jumps(self):
        self.assertEqual(core.pingpong_indices(4, 10), [0, 1, 2, 3, 2, 1, 0, 1, 2, 3])
        self.assertEqual(core.pingpong_indices(1, 3), [0, 0, 0])
        self.assertEqual(core.pingpong_indices(5, 3), [0, 1, 2])
        steps = core.pingpong_indices(7, 100)
        self.assertTrue(all(abs(a - b) == 1 for a, b in zip(steps, steps[1:])))
        with self.assertRaises(ValueError):
            core.pingpong_indices(0, 3)

    def test_extend_frames_keeps_frame_records(self):
        frames = [{"img_id": 10}, {"img_id": 11}, {"img_id": 12}]
        self.assertEqual([f["img_id"] for f in core.extend_frames(frames, 6)], [10, 11, 12, 11, 10, 11])

    def test_slim_train_frames(self):
        frames = [{"img_id": 0}, {"img_id": 5}, {"img_id": 9}, {"img_id": 3}]
        self.assertEqual(core.slim_train_frames(frames), [{"img_id": 0}, {"img_id": 9}])
        self.assertEqual(core.slim_train_frames([{"img_id": 4}]), [{"img_id": 4}])

    def test_volume_and_gain(self):
        self.assertEqual(core.parse_mean_volume("[Parsed] mean_volume: -27.3 dB\nmax_volume: -3.1 dB"), -27.3)
        self.assertIsNone(core.parse_mean_volume("mean_volume: -inf dB"))
        self.assertIsNone(core.parse_mean_volume("nothing"))
        self.assertEqual(core.gain_db(-30.0, -22.5), -7.5)
        self.assertEqual(core.gain_db(-30.0, -90.0), 30.0)
        self.assertEqual(core.gain_db(None, -20.0), 0.0)

    def test_slugify(self):
        self.assertEqual(core.slugify("Henry's Studio — Take 2!"), "henry-s-studio-take-2")
        self.assertEqual(core.slugify("???", "video"), "video")

    def test_foreign_processes_excludes_this_project(self):
        root = Path("/home/u/git/gaussian-talker")
        processes = [(1, f"{root}/.venv/bin/python render.py", f"{root}/third_party/GaussianTalker"),
                     (2, "/home/u/miniconda3/bin/python3 /home/u/git/maestro/train.py", "/home/u/git/maestro"),
                     (3, "python data_utils/face_parsing/test.py", f"{root}/third_party/GaussianTalker")]
        self.assertEqual([p[0] for p in core.foreign_processes(processes, root)], [2])

    def test_training_progress_reads_last_tqdm_update(self):
        log = ("Training progress:   0%|          | 0/7999 [00:00<?, ?it/s]\r"
               "Training progress:  50%|#####     | 4000/7999 [05:00<05:00, 13.3it/s]\n"
               "Training progress:  14%|#4        | 1420/10000 [30:45<3:06:04,  1.30s/it, Loss=0.06]\r")
        self.assertEqual(core.training_progress(log), {"stage": "fine", "iteration": 1420, "total": 10000, "percent": 14,
                                                       "overall": 52, "elapsed": "30:45", "remaining": "3:06:04"})
        coarse = "Training progress:  50%|#####     | 150/300 [00:10<00:10, 15it/s]"
        self.assertEqual(core.training_progress(coarse, 300, 600)["overall"], 17)
        self.assertIsNone(core.training_progress("no progress yet"))

    def test_config_iterations(self):
        text = "OptimizationParams = dict(\n    iterations=600,\n    coarse_iterations=300,\n)"
        self.assertEqual(core.config_iterations(text), (300, 600))
        self.assertEqual(core.config_iterations(""), (7999, 10000))
        self.assertEqual(core.config_iterations((ROOT / "backend/yatta/training/configs/deepspeech.py").read_text()), (7999, 10000))

    def test_log_events(self):
        text = "2026-10-20T14:09:08-07:00 prepare\nnoise line\n2026-10-20T14:48:10-07:00 GPU busy; waiting\n"
        self.assertEqual(core.log_events(text), [("2026-10-20T14:09:08-07:00", "prepare"),
                                                 ("2026-10-20T14:48:10-07:00", "GPU busy; waiting")])

    def test_npy_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.npy"
            write_npy(path, (527, 16, 44))
            self.assertEqual(core.npy_shape(path), (527, 16, 44))

    def test_registry_drops_variants_without_a_final_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m1/point_cloud/iteration_10000").mkdir(parents=True)
            (root / "m1/point_cloud/iteration_10000/point_cloud.ply").write_text("ply")
            registry = {"avatars": [
                {"id": "a", "name": "A", "variants": [
                    {"feature": "deepspeech", "model": "m1", "data": "d", "config": "c.py", "preview": "p.mp4"},
                    {"feature": "hubert", "model": "missing", "data": "d", "config": "c.py"}]},
                {"id": "b", "name": "B", "variants": [{"feature": "deepspeech", "model": "missing", "data": "d", "config": "c"}]}]}
            (root / "avatars.json").write_text(json.dumps(registry))
            avatars = core.load_registry(root / "avatars.json", root)
            self.assertEqual([a["id"] for a in avatars], ["a"])
            self.assertEqual([v["feature"] for v in avatars[0]["variants"]], ["deepspeech"])
            self.assertEqual(avatars[0]["variants"][0]["model"], str(root / "m1"))

    def test_studio_variants_need_done_marker_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            avatar = Path(tmp) / "avatars" / "me"
            for feature, done in (("esperanto", True), ("hubert", False)):
                run = avatar / "runs" / feature
                (run / "model/point_cloud/iteration_10000").mkdir(parents=True)
                (run / "model/point_cloud/iteration_10000/point_cloud.ply").write_text("ply")
                if done:
                    (run / "done").touch()
                    (run / "eval.json").write_text(json.dumps({"face_region": {"psnr": {"mean": 29.123}, "lpips": {"mean": 0.1234}}}))
            variants = core.studio_variants(avatar, ["esperanto", "hubert", "whisper"])
            self.assertEqual([v["feature"] for v in variants], ["esperanto"])
            self.assertEqual(variants[0]["metrics"], {"face_psnr": 29.12, "face_lpips": 0.123})
            self.assertTrue(variants[0]["data"].endswith("me/data/esperanto"))
            (avatar / "avatar.json").write_text(json.dumps({"id": "me", "name": "Me", "features": ["esperanto", "hubert"]}))
            studio = core.load_studio_avatars(Path(tmp))
            self.assertEqual([(a["id"], [v["feature"] for v in a["variants"]]) for a in studio], [("me", ["esperanto"])])

    def test_find_variant(self):
        avatars = [{"id": "a", "variants": [{"feature": "deepspeech"}, {"feature": "esperanto"}]}]
        self.assertEqual(core.find_variant(avatars, "a", "esperanto")[1], {"feature": "esperanto"})
        self.assertEqual(core.find_variant(avatars, "a", "whisper"), (None, None))
        self.assertEqual(core.find_variant(avatars, "a")[1], {"feature": "deepspeech"})  # no feature: the first
        avatars[0]["default_feature"] = "esperanto"
        self.assertEqual(core.find_variant(avatars, "a")[1], {"feature": "esperanto"})
        self.assertEqual(core.find_variant(avatars, "b"), (None, None))

    def test_split_at_pauses(self):
        self.assertEqual(core.split_at_pauses([], 10.0), [(0.0, 10.0)])
        # 30 s needs 3 pieces of ~10 s: cut at the pauses nearest 10 s and then 20 s
        self.assertEqual(core.split_at_pauses([(3.0, 3.4), (9.0, 9.6), (13.0, 13.4), (20.0, 20.6)], 30.0),
                         [(0.0, 9.3), (9.3, 20.3), (20.3, 30.0)])
        # just over the cap: two balanced pieces, never a sliver at the end
        self.assertEqual(core.split_at_pauses([(7.0, 7.4), (14.3, 14.5)], 14.6), [(0.0, 7.2), (7.2, 14.6)])
        # no pause in range: hard cut at the balanced point
        self.assertEqual(core.split_at_pauses([(1.0, 1.2)], 20.0), [(0.0, 10.0), (10.0, 20.0)])
        pieces = core.split_at_pauses([(i * 2.0, i * 2.0 + 0.3) for i in range(1, 150)], 300.0)
        self.assertTrue(all(b - a <= 14.5 for a, b in pieces) and pieces[-1][1] == 300.0)
        words = [[0.0, 0.6, "Hi,"], [0.7, 1.7, "I am Enrica."], [6.5, 7.0, "Today"], [7.1, 14.0, "we talk."],
                 [14.4, 20.0, "Bye."]]
        # 20 s needs two pieces of at most 13 s; the only gap that keeps both at least 5.2 s long is 7.0-7.1
        self.assertEqual(core.split_words(words, 20.0), [(0.0, 7.05, "Hi, I am Enrica. Today"), (7.05, 20.0, "we talk. Bye.")])
        self.assertEqual(core.split_words([[0.0, 3.0, "Short."]], 3.2), [(0.0, 3.2, "Short.")])
        self.assertEqual(core.parse_silences("silence_start: 1.25\nsilence_end: 1.5 | silence_duration: 0.25\n"), [(1.25, 1.5)])


if __name__ == "__main__":
    unittest.main()
