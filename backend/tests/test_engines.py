import unittest

from yatta import engines, services
from yatta.engines.base import Engine

QUICK = {"id": "q", "name": "Quick", "default_feature": "clip", "variants": [{"feature": "clip", "base": "/clip.mp4"}]}
TRAINED = {"id": "t", "name": "Trained", "default_feature": "esperanto",
           "variants": [{"feature": "esperanto", "data": "/identity", "model": "/model"}]}


class Installed(Engine):
    id, name, model, needs = "test", "Test", "Test model", "photo"


class EngineRegistryTests(unittest.TestCase):
    def test_every_engine_describes_itself(self):
        infos = engines.info()
        self.assertEqual([i["id"] for i in infos], list(engines.ENGINES))
        for info in infos:
            self.assertTrue(info["name"] and info["model"] and info["speed"] and info["licence"])
            self.assertIn(info["needs"], ("clip", "photo", "trained"))
            self.assertIsInstance(info["available"], bool)

    def test_what_an_engine_needs_decides_which_avatars_it_renders(self):
        clip, trained = Installed(), Installed()
        trained.needs = "trained"
        self.assertTrue(clip.supports(QUICK) and clip.supports(TRAINED))
        self.assertFalse(trained.supports(QUICK))
        self.assertTrue(trained.supports(TRAINED))

    def test_estimates(self):
        engine = Installed()
        engine.load_seconds, engine.seconds_per_second = 60, 13
        self.assertEqual(engine.estimate(10), 190)
        self.assertEqual(engine.speed(), "~3 min per 10 s of speech")
        engine.load_seconds, engine.seconds_per_second = 5, 1
        self.assertEqual(engine.speed(), "~15 s per 10 s of speech")

    def test_unknown_or_missing_engine_is_refused(self):
        queue = services.RenderQueue(worker=False)
        with self.assertRaisesRegex(ValueError, "unknown engine"):
            queue.submit({"avatar": "q", "engine": "nope", "voice": {"provider": "mms", "id": "eng"}})
        engines.ENGINES["test"] = Installed()
        Installed.available = lambda self: False
        try:
            with self.assertRaisesRegex(ValueError, "not installed"):
                queue.submit({"avatar": "q", "engine": "test", "voice": {"provider": "mms", "id": "eng"}})
        finally:
            del engines.ENGINES["test"]
            del Installed.available


if __name__ == "__main__":
    unittest.main()
