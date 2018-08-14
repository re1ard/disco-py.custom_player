# -*- coding: utf-8 -*-
import livestreamer
import subprocess
import sys

def main(args):
	chunk_size = 16384
	url = u"hls://{}".format(args[1])
	stream = livestreamer.streams(url)['worst'].open()
	###############################################################
	ffmpeg_args = u"avconv -i pipe:0".split() + args[2:]
	process = subprocess.Popen(ffmpeg_args,stdin = subprocess.PIPE)
	###############################################################
	data = stream.read(chunk_size)
	while data:
		process.stdin.write(data)
		data = stream.read(chunk_size)

	process.kill()
	return

if __name__ == "__main__":
	main(sys.argv)