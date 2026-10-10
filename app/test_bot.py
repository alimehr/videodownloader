import sys
import tempfile
from pathlib import Path
import unittest
import bot

class Links(unittest.TestCase):
    def test_supported(self):
        for url in ['https://youtu.be/dQw4w9WgXcQ?t=5', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=123', 'https://youtube.com/shorts/dQw4w9WgXcQ']:
            self.assertEqual(bot.video_id(url), 'dQw4w9WgXcQ')
    def test_reject(self):
        for url in ['https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ', 'https://youtube.com@127.0.0.1/watch?v=dQw4w9WgXcQ', 'http://127.0.0.1/', 'https://youtube.com/playlist?list=abc', 'https://youtu.be/bad', 'https://youtube.com:8888/watch?v=dQw4w9WgXcQ']:
            self.assertIsNone(bot.video_id(url))

class Processes(unittest.IsolatedAsyncioTestCase):
    async def test_stdout(self):
        self.assertEqual(await bot.run_process([sys.executable, '-c', 'print(123)'], 5), '123\n')
    async def test_timeout(self):
        with self.assertRaisesRegex(ValueError, 'زمان'):
            await bot.run_process([sys.executable, '-c', 'import time; time.sleep(30)'], .1)
    async def test_size_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with (folder/'large.part').open('wb') as f:
                f.truncate(150_000_001)
            with self.assertRaisesRegex(ValueError, 'بزرگ'):
                await bot.run_process([sys.executable, '-c', 'import time; time.sleep(30)'], 5, folder)
    async def test_error_sanitized(self):
        with self.assertRaises(ValueError) as result:
            await bot.run_process([sys.executable, '-c', 'import sys; sys.stderr.write("secret"); sys.exit(1)'], 5)
        self.assertNotIn('secret', str(result.exception))

if __name__ == '__main__':
    unittest.main()
