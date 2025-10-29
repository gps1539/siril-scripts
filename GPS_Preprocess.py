"""
**Preprocessing script using sirilpy**

This script executes siril commands to calibrate, register and stack subs. It accepts argruments to define working directory, bkg extraction, platesolving, filters, feathering and drizzing setting. It can run headlessly i.e. without the siril UI open, so it can run on a server or cloud instance.

The script supports mosaics when the platesolving option is selected. 

Currently the script can no be started directly from siril-cli, but it can be started from a ssf script using the 'pyscript' command i.e. pyscript GPS_Preprocess.py. Such a ssf script can run the script several times (for different settings) with unique saved result files based on setting values. The script skips restacking master biases, flats, darks, background exaction and/or platesolving if they already exist. 

Example ssf script 
----
requires 1.3.6
pyscript GPS_Preprocess.py -d <your-working-directory-path> -b 95% -r 85% -w 85% -z 1 -ps -bg
---

Preprocessing for Siril
from Graham Smith (2025)

SPDX-License-Identifier: GPL-3.0-or-later
"""


import sys
import os
import sirilpy as s
import argparse

# command line options and help
parser = argparse.ArgumentParser()
parser.add_argument("-b","--background", nargs='+', help="background filter settings, XX% or Xk")
parser.add_argument("-bg","--bkg", help="extract background" ,action="store_true")
parser.add_argument("-d","--workdir", nargs='+', help="set working directory")
parser.add_argument("-f","--feather", nargs='+', help="set feathering amount in px")
parser.add_argument("-ps","--platesolve", help="platesolve" ,action="store_true")
parser.add_argument("-r","--round", nargs='+', help="round filter settings, XX% or Xk")
parser.add_argument("-w","--wfwhm", nargs='+', help="wfwhm filter settings, XX% or Xk")
parser.add_argument("-z","--drizzle", nargs='+', help="sets drizzle scaling, default =1X")
args = parser.parse_args()

siril = s.SirilInterface()

VERSION = "0.0.5"


# ==============================================================================
# Prototype sirilpy preprocessing script
# ==============================================================================

def master_bias(bias_dir, process_dir):
	if os.path.exists ((workdir) + '/process/bias_stacked.fit'):
		print('master bias exists, skipping')
		return		
	else:
		siril.cmd("cd " + bias_dir )
		siril.cmd("convert bias -out=" + process_dir)
		siril.cmd("cd " + process_dir)
		siril.cmd("stack bias rej 3 3  -nonorm")
    
def master_flat(flat_dir, process_dir):
	if os.path.exists ((workdir) + '/process/pp_flat_stacked.fit'):
		print('master flat exists, skipping')
		return		
	else:
		siril.cmd("cd " + flat_dir )
		siril.cmd("convert flat -out=" + process_dir)
		siril.cmd("cd " + process_dir)
		siril.cmd("calibrate flat  -bias=bias_stacked")
		siril.cmd("stack  pp_flat rej  3 3 -norm=mul")
    
def master_dark(dark_dir, process_dir):
	if os.path.exists ((workdir) + '/process/dark_stacked.fit'):
		print('master dark exists, skipping')
		return		
	else:
		siril.cmd("cd " + dark_dir )
		siril.cmd("convert dark -out=" + process_dir)
		siril.cmd("cd " + process_dir)
		siril.cmd("stack dark rej 3 3 -nonorm")
    
def light(light_dir, process_dir):
	if os.path.exists ((workdir) + '/process/pp_light_.seq'):
		print('pp_light exists, skipping')
		return		
	else:
		siril.cmd("cd " + light_dir)
		siril.cmd("convert light -out=" + process_dir)
		siril.cmd("cd " + process_dir )
		siril.cmd("calibrate light -dark=dark_stacked -flat=pp_flat_stacked -cc=dark -cfa -equalize_cfa")

def bkg_extract(process_dir):
	if os.path.exists ((workdir) + '/process/bkg_pp_light_.seq'):
		print('background extracted, skipping')
		return		
	else:
		siril.cmd("cd " + process_dir)
		siril.cmd("seqsubsky pp_light 1 -samples=10")
	
def platesolve(process_dir):
	if args.bkg:
		if os.path.exists ((workdir) + '/process/r_bkg_pp_light_.seq'):
			print('sequence platesolved, skipping')
			return			
	else:
		if os.path.exists ((workdir) + '/process/r_pp_light_.seq'):
			print('sequence platesolved, skipping')
			return		

	siril.cmd("cd " + process_dir)
	siril.cmd("seqplatesolve " + light_seq + " -nocache -catalog=nomad -force -disto=ps_distortion")

def register(process_dir):
	siril.cmd("cd " + process_dir)
	if args.platesolve:
		siril.cmd("seqapplyreg " + light_seq + " -framing=max -filter-bkg=" + bkg + " -filter-round=" + roundf + " -filter-wfwhm=" + wfwhm + " -kernel=square -drizzle -scale=" + drizzle_scale + " -pixfrac=" + pix_frac + " -flat=pp_flat_stacked")
	else :
		siril.cmd("register bkg_pp_light -2pass")
		siril.cmd("seqapplyreg " + light_seq + " -filter-bkg=" + bkg + " -filter-round=" + roundf + " -filter-wfwhm=" + wfwhm + " -kernel=square -drizzle -scale=" + drizzle_scale + " -pixfrac=" + pix_frac + " -flat=pp_flat_stacked")

def stack(process_dir):
	siril.cmd("cd " + process_dir)	
	siril.cmd("stack r_" + light_seq + " rej 3 3 -norm=addscale -output_norm -rgb_equal -maximize -filter-included -weight=wfwhm  -feather=" + feather + " -out=../result-bkg_"+bkg+"-round_"+roundf+"-wfwhm_"+wfwhm+"-drizzle_"+drizzle_scale+"-feather_"+feather)
	siril.cmd("close")
    
# ==============================================================================
bkg = (args.background[0]) if args.background else '3k'
roundf = (args.round[0]) if args.round else '3k'
wfwhm = (args.wfwhm[0]) if args.wfwhm else '3k'
drizzle_scale = args.drizzle[0] if args.drizzle else '1'
pix_frac = str(1 / float(drizzle_scale))
feather = args.feather[0] if args.feather else '0'
# ==============================================================================	
try:
	siril.connect()
	siril.cmd("requires", "1.3.6")	
	siril.log("Running preprocessing")
	workdir = args.workdir[0]
	siril.cmd("cd", workdir)
	process_dir = '../process'
	siril.cmd("set32bits")
	siril.cmd("setext fit")
	master_bias(workdir+ '/biases' ,process_dir)
	master_flat(workdir+ '/flats'  ,process_dir)
	master_dark(workdir+ '/darks'  ,process_dir)
	light(workdir+ '/lights' ,process_dir)
	if args.bkg: 
		bkg_extract(workdir+ '/process')
		light_seq = 'bkg_pp_light'
	else:
		light_seq = 'pp_light'
	if args.platesolve: platesolve(workdir+ '/process')
	register(workdir+ '/process')
	stack(workdir+ '/process')
except Exception as e :
	print("\n**** ERROR *** " +  str(e) + "\n" )


