"""
**Postprocessing script using sirilpy**

This script executes siril commands for background extraction, denoise and/or sharpening. It accepts arguments to define working directory, strenghts, amounts etc. It can run headlessly i.e. without the siril UI open, so it can run on a server or cloud instance.

With the CosmicClarity and GraXpert the executables must be installed and configured using their sirilpy scripts 1st.

The script can be started directly from the siril command line and can also be started from a ssf script using the 'pyscript' command i.e. pyscript GPS_Postprocess.py. Such a ssf script can run the script several times i.e. to try different settings. The commands will postprocess all fit(s) files found in the supplied working directory.

Example ssf script to run this script
---
requires 1.3.6
pyscript GPS_Postprocess.py -d /home/grahams/astro/workspace -dc 0.5
pyscript GPS_Postprocess.py -d /home/grahams/astro/workspace -sc 0.5 0.5 5
---

Postprocessing for Siril
from Graham Smith (2025)

SPDX-License-Identifier: GPL-3.0-or-later
"""

import sys
import os
import subprocess
import shutil
import sirilpy as s
import argparse
import re

# command line options and help
parser = argparse.ArgumentParser()
parser.add_argument("-b","--bkg", nargs='+', help="siril background extraction, provide smoothing 0.0-1.0")
parser.add_argument("-bg","--bkgGraX", nargs='+', help="siril background extraction, provide smoothing 0.0-1.0")
parser.add_argument("-d","--workdir", nargs='+', help="set working directory")
parser.add_argument("-dc","--denoiseCC", nargs='+', help="run CC denoise, provide denoise strength 0.0-1.0")
parser.add_argument("-dg","--denoiseGraX", nargs='+', help="denoise using GraXpert-AI, provide strength 0.0-1.0")
parser.add_argument("-s","--sharpen", help="sharpen (deconvolution)" ,action="store_true")
parser.add_argument("-sc","--sharpenCC", nargs='+', help="run CC sharpen, provide stellar_amount, non_stellar_amount and non_stellar_strength")
parser.add_argument("-sg","--sharpenGraX", nargs='+', help="sharpen (deconvolution) using GraXpert-AI, provide strength 0.0-1.0")
args = parser.parse_args()

siril = s.SirilInterface()

VERSION = "0.0.5"


# ==============================================================================
# Prototype sirilpy postprocessing script
# ==============================================================================

def bkg(workdir):
	os.chdir(workdir)
	for image in os.listdir():
		if image.endswith(".fits") or image.endswith(".fit"):
			siril.log("Starting background extraction on " + image)
			siril.cmd("load", image)
			siril.cmd("subsky -rbf -samples=20 -tolerance=1.0 -smooth=" + smooth)
			siril.cmd("save", image)

def bkg_GraX(workdir):
	os.chdir(workdir)
	for image in os.listdir():
		if image.endswith(".fits") or image.endswith(".fit"):
			siril.log("Starting GraXpert background extraction on " + image)			
			siril.cmd("load", image)
			siril.cmd("pyscript GraXpert-AI.py -gpu -bge -smoothing " + bkgGraX)
			siril.cmd("save", image)

def denoise_CC(workdir):
# find CosmicClaritySuitepath paths
	if os.path.isfile (os.path.join((os.path.expanduser("~")), '.config', 'siril', 'sirilcc_denoise.conf')):
		config_file_path = os.path.join((os.path.expanduser("~")), '.config', 'siril', 'sirilcc_denoise.conf')
		with open(config_file_path, 'r') as file:
			executable_path = file.readline().strip()
			cc_input_dir = (executable_path.rsplit('/', 1)[0])+"/input"
			cc_output_dir = (executable_path.rsplit('/', 1)[0])+"/output"
	else:
		print("Executable not yet configured. It is recommended to use Seti Astro Cosmic Clarity v5.4 or higher.")
		sys.exit(1)

	os.chdir(workdir)
	for image in os.listdir():
		if image.endswith(".fits") or image.endswith(".fit"):
			siril.log(image)
			shutil.copy(image, cc_input_dir)			
			cmd = f"{executable_path} --denoise_strength {denoiseCC_strength} --denoise_mode full"
			process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)

			percent_re = re.compile(r"(\d+\.?\d*)%")
			if process.stdout:
				for line in iter(process.stdout.readline, ''):
					line = line.strip()
					if not line:
						continue
					m = percent_re.search(line)
					if m:
						try:
							pct = float(m.group(1))
							siril.update_progress(f"Denoise: {pct:.2f}%", pct / 100.0)
						except ValueError:
							siril.log(line)
					else:
						siril.log(line)
			process.wait()
        
	os.chdir(cc_input_dir)
	for image in os.listdir():
		os.remove(image)
	os.chdir(cc_output_dir)
	for image in os.listdir():
		print(image)
		shutil.move(image, workdir)
					
def denoise_GraX(workdir):
	os.chdir(workdir)
	for image in os.listdir():
		if image.endswith(".fits") or image.endswith(".fit"):
			siril.log("Starting GraXpert denoise on " + image)
			siril.cmd("load", image)
			siril.cmd("pyscript GraXpert-AI.py -gpu -denoise -strength " + denoiseGraX)
			siril.cmd("save", image)
			 
def sharpen(workdir):
	os.chdir(workdir)
	for image in os.listdir():
		if image.endswith(".fits") or image.endswith(".fit"):
			siril.log("Starting sharpen on " + image)
			siril.cmd("load", image)
			siril.cmd("rl -gdstep=0.0003 -iters=40 -alpha=3000 -tv")
			siril.cmd("rl -gdstep=0.0002 -iters=40 -alpha=3000 -tv")
			siril.cmd("save", image)

def sharpen_CC(workdir):
# find CosmicClaritySuitepath paths
	if os.path.isfile (os.path.join((os.path.expanduser("~")), '.config', 'siril', 'sirilcc_sharpen.conf')):
		config_file_path = os.path.join((os.path.expanduser("~")), '.config', 'siril', 'sirilcc_sharpen.conf')
		with open(config_file_path, 'r') as file:
			executable_path = file.readline().strip()
			cc_input_dir = (executable_path.rsplit('/', 1)[0])+"/input"
			cc_output_dir = (executable_path.rsplit('/', 1)[0])+"/output"
	else:
		print("Executable not yet configured. It is recommended to use Seti Astro Cosmic Clarity v5.4 or higher.")
		sys.exit(1)
		
	os.chdir(workdir)
	for image in os.listdir():
		if image.endswith(".fits") or image.endswith(".fit"):
			shutil.copy(image, cc_input_dir)

			cmd = f"{executable_path} --nonstellar_strength {sharpenCC_non_stellar_strength} --stellar_amount {sharpenCC_stellar} --nonstellar_amount  {sharpenCC_non_stellar} --auto_detect_psf --sharpening_mode Both"

			process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)

			percent_re = re.compile(r"(\d+\.?\d*)%")
			if process.stdout:
				for line in iter(process.stdout.readline, ''):
					line = line.strip()
					if not line:
						continue
					m = percent_re.search(line)
					if m:
						try:
							pct = float(m.group(1))
							siril.update_progress(f"Sharpen: {pct:.2f}%", pct / 100.0)
						except ValueError:
							siril.log(line)
					else:
						siril.log(line)
			process.wait()

	os.chdir(cc_input_dir)
	for image in os.listdir():
		os.remove(image)
	os.chdir(cc_output_dir)
	for image in os.listdir():
		print(image)
		shutil.move(image, workdir)

def sharpen_GraX(workdir):
	os.chdir(workdir)
	for image in os.listdir():
		if image.endswith(".fits") or image.endswith(".fit"):
			siril.log("Starting GraXpert sharpen on " + image)
			siril.cmd("load", image)
			siril.cmd("pyscript GraXpert-AI.py -gpu -deconv_obj -strength " + sharpenGraX)
			siril.cmd("pyscript GraXpert-AI.py -gpu -deconv_stellar -strength " + sharpenGraX)
			siril.cmd("save", image)			
	
# ==============================================================================	

try:
	siril.connect()
	siril.cmd("requires", "1.3.6")	
	siril.log("Running postprocessing")
	workdir = args.workdir[0] if args.workdir else os.getcwd()	
	siril.cmd("cd", workdir)
	siril.cmd("set32bits")
	siril.cmd("setext fit")
except Exception as e :
	print("\n**** ERROR *** " +  str(e) + "\n" )

if args.bkg:
	smooth = (args.bkg[0])
	bkg(workdir)

if args.bkgGraX:
	bkgGraX = (args.bkgGraX[0])
	bkg_GraX(workdir)

if args.sharpen:
	sharpen(workdir)

if args.denoiseCC:
	denoiseCC_strength = (args.denoiseCC[0])
	denoise_CC(workdir)
	
if args.sharpenCC:
	sharpenCC_stellar = (args.sharpenCC[0])
	sharpenCC_non_stellar = (args.sharpenCC[1])	
	sharpenCC_non_stellar_strength = (args.sharpenCC[2])
	sharpen_CC(workdir)
	
if args.denoiseGraX:
	denoiseGraX = (args.denoiseGraX[0])
	denoise_GraX(workdir)
		
if args.sharpenGraX:
	sharpenGraX = (args.sharpenGraX[0])
	sharpen_GraX(workdir)
