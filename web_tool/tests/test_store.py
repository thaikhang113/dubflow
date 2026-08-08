import tempfile
import threading
import unittest
from pathlib import Path

from web_tool.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "tool.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_fifo_claim_allows_one_running_job(self):
        first = self.store.enqueue_job(
            {
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1",
            }
        )
        second = self.store.enqueue_job(
            {
                "platform": "douyin",
                "source": "https://www.douyin.com/video/2",
            }
        )
        claimed = self.store.claim_next_job()
        self.assertEqual(first["id"], claimed["id"])
        self.assertIsNone(self.store.claim_next_job())
        self.store.update_job(first["id"], state="completed")
        self.assertEqual(second["id"], self.store.claim_next_job()["id"])

    def test_restart_recovery_requires_resume(self):
        job = self.store.enqueue_job(
            {
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1",
            }
        )
        self.store.claim_next_job()
        self.assertEqual(1, self.store.recover_running_jobs())
        recovered = self.store.get_job(job["id"])
        self.assertEqual("needs_attention", recovered["state"])
        self.assertEqual("resume", recovered["action"])
        self.assertIsNone(recovered["pid"])

    def test_paused_queue_does_not_claim(self):
        self.store.enqueue_job(
            {
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1",
            }
        )
        self.store.set_queue_paused(True)
        self.assertIsNone(self.store.claim_next_job())
        self.store.set_queue_paused(False)
        self.assertIsNotNone(self.store.claim_next_job())

    def test_concurrent_claims_return_only_one_job(self):
        self.store.enqueue_job(
            {
                "platform": "bilibili",
                "source": "https://www.bilibili.com/video/BV1",
            }
        )
        barrier = threading.Barrier(3)
        results = []

        def claim():
            barrier.wait()
            results.append(Store(self.store.path).claim_next_job())

        workers = [threading.Thread(target=claim) for _ in range(2)]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join()

        self.assertEqual(1, sum(result is not None for result in results))


if __name__ == "__main__":
    unittest.main()
