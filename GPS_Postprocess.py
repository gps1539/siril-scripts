"""
**Postprocessing script using sirilpy**



Preprocessing for Siril
from Graham Smith (2025)

SPDX-License-Identifier: GPL-3.0-or-later
"""


import sys
import os
import subprocess
import shutil
import sirilpy as s
import argparse

# command line options and help
parser = argparse.ArgumentParser()
parser.add_argument("-b","--bkg", nargs='+', help="siril background extraction, provide smoothing 0.0-1.0")
parser.add_argument("-bg","--bkgGraX", nargs='+', help="siril background extraction, provide smoothing 0.0-1.0")
parser.add_argument("-d","--workdir", nargs='+', help="set working directory")
parser.add_argument("-dc","--denoiseCC", nargs='+', help="run CC denoise, provide path to SetiAstroCosmicClarity_denoise executable and denoise strength 0.0-1.0")
parser.add_argument("-dg","--denoiseGraX", nargs='+', help="denoise using GraXpert-AI, provide strength 0.0-1.0")
parser.add_argument("-s","--sharpen", help="sharpen (deconvolution)" ,action="store_true")
parser.add_argument("-sc","--sharpenCC", nargs='+', help="run CC sharpen, provide provide path to SetiAstroCosmicClarity executable, stellar_amount, non_stellar_amount and non_stellar_strength")
parser.add_argument("-sg","--sharpenGraX", nargs='+', help="sharpen (deconvolution) using GraXpert-AI, provide strength 0.0-1.0")
parser.add_argument("-r","--round", nargs='+', help="round filter settings, XX% or Xk")
parser.add_argument("-w","--wfwhm", nargs='+', help="wfwhm filter settings, XX% or Xk")
parser.add_argument("-z","--drizzle", nargs='+', help="sets drizzle scaling, default =1X")
args = parser.parse_args()

siril = s.SirilInterface()

VERSION = "0.0.1"


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
	os.chdir(workdir)
	cc_input_dir='/home/grahams/astro/CosmicClaritySuite_Linux/input'
	cc_output_dir='/home/grahams/astro/CosmicClaritySuite_Linux/output'
	for image in os.listdir():
		if image.endswith(".fits") or image.endswith(".fit"):
			siril.log(image)
			shutil.copy(image, cc_input_dir)			
			siril.log("Starting subprocess for CosmicClarity on " + image + ", there will be no output until complete.")
			process = subprocess.Popen([denoiseCC_path + " --denoise_strength " + denoiseCC_strength + " --denoise_mode full" ], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
			stdout, stderr = process.communicate()  # This prevents hanging

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
	os.chdir(workdir)
	cc_input_dir='/home/grahams/astro/CosmicClaritySuite_Linux/input'
	cc_output_dir='/home/grahams/astro/CosmicClaritySuite_Linux/output'
	for image in os.listdir():
		if image.endswith(".fits") or image.endswith(".fit"):
			shutil.copy(image, cc_input_dir)
			siril.log("Starting subprocess for CosmicClarity on " + image + ", there will be no output until complete.")		
			process = subprocess.Popen(["/home/grahams/astro/CosmicClaritySuite_Linux/SetiAstroCosmicClarity --sharpening_mode Both --auto_detect_psf --nonstellar_strength " + sharpenCC_non_stellar_strength + " --stellar_amount " + sharpenCC_stellar + " --nonstellar_amount " + sharpenCC_non_stellar + " --sharpen_channels_separately"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
			stdout, stderr = process.communicate()  # This prevents hanging

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
	workdir = args.workdir[0]
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
	denoiseCC_path = (args.denoiseCC[0])
	denoiseCC_strength = (args.denoiseCC[1])
	denoise_CC(workdir)
	
if args.sharpenCC:
	sharpenCC_path = (args.sharpenCC[0])
	sharpenCC_stellar = (args.sharpenCC[1])
	sharpenCC_non_stellar = (args.sharpenCC[2])	
	sharpenCC_non_stellar_strength = (args.sharpenCC[3])
	sharpen_CC(workdir)
	
if args.denoiseGraX:
	denoiseGraX = (args.denoiseGraX[0])
	denoise_GraX(workdir)
		
if args.sharpenGraX:
	sharpenGraX = (args.sharpenGraX[0])
	sharpen_GraX(workdir)
