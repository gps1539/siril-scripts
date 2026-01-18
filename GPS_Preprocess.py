"""
**Preprocessing script using sirilpy**

This script executes siril commands to calibrate, background extract(optional), platesolve(optional), register and stack subs. It accepts arguments to define working directory, filters, feathering and drizzling setting. It can run headlessly i.e. without the siril UI open, so it can run on a server or cloud instance.

With the platesolving option the script can register mosaics.

The script can be started directly from the siril GUI, siril command line and can also be started from a ssf script using the 'pyscript' command i.e. pyscript GPS_Preprocess.py. Such a ssf script can run the this script several times i.e. to try different settings, with unique result files based on setting values. 

The script also skips restacking master biases, flats, darks, background exaction and platesolving if they already exist. 

Example ssf script to run this script
---
requires 1.3.6
pyscript GPS_Preprocess.py -d <your-workspace-directory-path> -b 95% -r 85% -w 85% -z 1 -ps -bg
---

Preprocessing for Siril
from Graham Smith (2025)

SPDX-License-Identifier: GPL-3.0-or-later
-----
0.1.1	Initial submittal for merge request
 
"""


import sys
import os
import sirilpy as s
import argparse
import re

VERSION = "0.1.1"
	
# PyQt6 for GUI
try:
	from PyQt6.QtWidgets import (
		QApplication, QDialog, QLabel, QLineEdit, QPushButton, QCheckBox,
		QVBoxLayout, QHBoxLayout, QFormLayout, QDialogButtonBox, QMessageBox
	)
except ImportError:
	# Silently fail if PyQt6 is not installed, as it's optional for CLI mode.
	pass


# ==============================================================================
# Prototype sirilpy preprocessing script
# ==============================================================================

def master_bias(bias_dir, process_dir):
	if os.path.exists(os.path.join(workdir, 'process/bias_stacked.fit')):
		print('master bias exists, skipping')
		return
	else:
		siril.cmd(f"cd {bias_dir}")
		siril.cmd(f"convert bias -out={process_dir}")
		siril.cmd(f"cd  {process_dir}")
		siril.cmd(f"stack bias rej 3 3 -nonorm")


def master_flat(flat_dir, process_dir):
	if os.path.exists(os.path.join(workdir, 'process/pp_flat_stacked.fit')):
		print('master flat exists, skipping')
		return
	else:
		siril.cmd(f"cd {flat_dir}")
		siril.cmd(f"convert flat -out={process_dir}")
		siril.cmd(f"cd {process_dir}")
		siril.cmd("calibrate flat -bias=bias_stacked")
		siril.cmd("stack pp_flat rej 3 3 -norm=mul")


def master_dark(dark_dir, process_dir):
	if os.path.exists(os.path.join(workdir, 'process/dark_stacked.fit')):
		print('master dark exists, skipping')
		return
	else:
		siril.cmd(f"cd {dark_dir}")
		siril.cmd(f"convert dark -out={process_dir}")
		siril.cmd(f"cd {process_dir}")
		siril.cmd(f"stack dark rej 3 3 -nonorm")


def light(light_dir, process_dir):
	if os.path.exists(os.path.join(workdir, 'process/pp_light_.seq')):
		print('pp_light exists, skipping')
		return
	else:
		siril.cmd(f"cd {light_dir}")
		siril.cmd(f"convert light -out={process_dir}")
		siril.cmd(f"cd {process_dir}")
		siril.cmd(
			f"calibrate light -dark=dark_stacked -flat=pp_flat_stacked -cc=dark -cfa -equalize_cfa")


def light_nc(light_dir, process_dir):
	if os.path.exists(os.path.join(workdir, 'process/pp_light_.seq')):
		print('pp_light exists, skipping')
		return
	else:
		siril.cmd(f"cd {light_dir}")
		siril.cmd(f"convert pp_light -out={process_dir}")


def bkg_extract(process_dir):
	if os.path.exists(os.path.join(workdir, 'process/bkg_pp_light_.seq')):
		print('background extracted, skipping')
		return
	else:
		siril.cmd(f"cd {process_dir}")
		siril.cmd(f"seqsubsky pp_light 1 -samples=10")


def platesolve(process_dir):
	if args.bkg:
		if os.path.exists(os.path.join(workdir, 'process/r_bkg_pp_light_.seq')):
			print('sequence platesolved, skipping')
			return
	else:
		if os.path.exists(os.path.join(workdir, 'process/r_pp_light_.seq')):
			print('sequence platesolved, skipping')
			return
	siril.cmd("cd " + process_dir)
	siril.cmd(
		f"seqplatesolve {light_seq} -nocache -catalog=nomad -force -disto=ps_distortion")


def register(process_dir):
	siril.cmd(f"cd {process_dir}")
	flat = " " if args.no_calibration else " -flat=pp_flat_stacked"
	if args.platesolve:
		siril.cmd(
			f"seqapplyreg {light_seq} -framing=max -filter-bkg={bkg} -filter-round={roundf} -filter-wfwhm={wfwhm} {drizzle} {flat}")
	else:
		siril.cmd(f"register {light_seq} -2pass")
		siril.cmd(
			f"seqapplyreg {light_seq} -filter-bkg={bkg} -filter-round={roundf} -filter-wfwhm={wfwhm} {drizzle} {flat}")

def stack(process_dir):
	siril.cmd(f"cd {process_dir}")
	siril.cmd("load pp_light_00001.fit")
	try:
		obj = (siril.get_image_fits_header(return_as='dict')['OBJECT']).replace(" ", "")
	except KeyError:
		obj = ("")
	siril.cmd(f"stack r_{light_seq} rej 3 3 -norm=addscale -output_norm -rgb_equal -maximize -filter-included -weight=wfwhm  -feather={feather} -out=../{obj}_b{bkg}-r{roundf}-w{wfwhm}-z{drizzle_scale}-f{feather}-$LIVETIME:%d$s")
	siril.cmd("close")

# ==============================================================================
# GUI Mode
# ==============================================================================


def run_gui():
	if 'QApplication' not in globals():
		print("PyQt6 is not installed. Please install it to use the GUI.")
		print("pip install PyQt6")
		return

	class PreprocessingDialog(QDialog):
		def __init__(self, parent=None):
			super().__init__(parent)
			self.setWindowTitle("Siril Pre-processing")
			self.setFixedWidth(int(self.width() * 1.10))

			layout = QVBoxLayout(self)
			form_layout = QFormLayout()

			try:
				self.workdir_input = QLineEdit(os.getcwd())
				form_layout.addRow("Working Directory:", self.workdir_input)
			except Exception as e:
				print("Working directory does not exist:", e)
				sys.exit(1)

			self.background_input = QLineEdit("100%")
			form_layout.addRow(
				"Background filter (XX% or X):", self.background_input)

			self.round_input = QLineEdit("100%")
			form_layout.addRow("Round filter (XX% or X):", self.round_input)

			self.wfwhm_input = QLineEdit("100%")
			form_layout.addRow("wFWHM filter (XX% or X):", self.wfwhm_input)

			self.feather_input = QLineEdit("0")
			form_layout.addRow("Feathering (px):", self.feather_input)

			self.drizzle = QCheckBox("Drizzle (scale), enable for OSC")
			self.drizzle_input = QLineEdit("1")
			self.drizzle_input.setEnabled(False)
			self.drizzle.toggled.connect(self.drizzle_input.setEnabled)
			drizzle_layout = QHBoxLayout()
			drizzle_layout.addWidget(self.drizzle_input)
			form_layout.addRow(self.drizzle, drizzle_layout)
			
			self.bkg_extract_cb = QCheckBox("Extract Background")
			form_layout.addRow(self.bkg_extract_cb)

			self.no_calibration_cb = QCheckBox("No Calibration")
			form_layout.addRow(self.no_calibration_cb)

			self.platesolve_cb = QCheckBox("Platesolve")
			form_layout.addRow(self.platesolve_cb)

			layout.addLayout(form_layout)

			self.button_box = QDialogButtonBox(
				QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
			self.button_box.accepted.connect(self.accept)
			self.button_box.rejected.connect(self.reject)
			layout.addWidget(self.button_box)

		def get_values(self):
			return {
				"workdir": self.workdir_input.text(),
				"background": self.background_input.text(),
				"round": self.round_input.text(),
				"wfwhm": self.wfwhm_input.text(),
				"feather": self.feather_input.text(),
				"drizzle": self.drizzle_input.text() if self.drizzle.isChecked() else None,
				"bkg_extract": self.bkg_extract_cb.isChecked(),
				"no_calibration": self.no_calibration_cb.isChecked(),
				"platesolve": self.platesolve_cb.isChecked(),
			}

	app = QApplication.instance() or QApplication(sys.argv)
	dialog = PreprocessingDialog()
	if dialog.exec():
		values = dialog.get_values()

		cli_args = []
		if values["workdir"]:
			cli_args.extend(["-d", values["workdir"]])
		if values["background"]:
			cli_args.extend(["-b", values["background"]])
		if values["round"]:
			cli_args.extend(["-r", values["round"]])
		if values["wfwhm"]:
			cli_args.extend(["-w", values["wfwhm"]])
		if values["feather"]:
			cli_args.extend(["-f", values["feather"]])
		if values["drizzle"]:
			cli_args.extend(["-z", values["drizzle"]])
		if values["bkg_extract"]:
			cli_args.append("-bg")
		if values["no_calibration"]:
			cli_args.append("-nc")
		if values["platesolve"]:
			cli_args.append("-ps")

		main_logic(cli_args)

		msg_box = QMessageBox()
		msg_box.setIcon(QMessageBox.Icon.Information)
		msg_box.setText("Processing finished.")
		msg_box.setWindowTitle("Success")
		msg_box.exec()


def main_logic(argv):
#	global args, workdir, bkg, roundf, wfwhm, drizzle_scale, pix_frac, feather, light_seq
	global args, workdir, bkg, roundf, wfwhm, drizzle, drizzle_scale, feather, light_seq

	parser = argparse.ArgumentParser()
	parser.add_argument("-b", "--background", nargs='+',
						help="background filter settings, XX%% or X")
	parser.add_argument(
		"-bg", "--bkg", help="extract background", action="store_true")
	parser.add_argument("-d", "--workdir", nargs='+',
						help="set working directory")
	parser.add_argument("-f", "--feather", nargs='+',
						help="set feathering amount in px")
	parser.add_argument("-nc", "--no_calibration",
						help="do not calibrate", action="store_true")
	parser.add_argument("-ps", "--platesolve",
						help="platesolve", action="store_true")
	parser.add_argument("-r", "--round", nargs='+',
						help="round filter settings, XX%% or X")
	parser.add_argument("-w", "--wfwhm", nargs='+',
						help="wfwhm filter settings, XX%% or X")
	parser.add_argument("-z", "--drizzle", nargs='+',
						help="sets drizzle scaling, default =1X")
	args = parser.parse_args(argv)

	bkg = (args.background[0]) if args.background else '100%'
	roundf = (args.round[0]) if args.round else '100%'
	wfwhm = (args.wfwhm[0]) if args.wfwhm else '100%'
	if args.drizzle:
		drizzle_scale = args.drizzle[0]
		pix_frac = str(1 / float(drizzle_scale))
		drizzle = f"-kernel=square -drizzle -scale={drizzle_scale} -pixfrac={pix_frac}"
	else:
		drizzle, drizzle_scale = " ", 0
	feather = args.feather[0] if args.feather else '0'

	try:
		siril.connect()
		siril.cmd("requires", "1.3.6")
		siril.log("Running preprocessing")
		workdir = args.workdir[0] if args.workdir else os.getcwd()
		siril.cmd("cd", workdir)
		process_dir = os.path.join(workdir, 'process')
		if not os.path.exists(process_dir):
			os.makedirs(process_dir)

		siril.cmd("set32bits")
		siril.cmd("setext", "fit")
		if args.no_calibration:
			light_nc(os.path.join(workdir, 'lights'), process_dir)
		else:
			master_bias(os.path.join(workdir, 'biases'), process_dir)
			master_flat(os.path.join(workdir, 'flats'), process_dir)
			master_dark(os.path.join(workdir, 'darks'), process_dir)
			light(os.path.join(workdir, 'lights'), process_dir)
		if args.bkg:
			bkg_extract(process_dir)
			light_seq = 'bkg_pp_light'
		else:
			light_seq = 'pp_light'
		if args.platesolve:
			platesolve(process_dir)
		register(process_dir)
		stack(process_dir)
		siril.cmd("cd", workdir)
	except Exception as e:
		print("\n**** ERROR *** " + str(e) + "\n")
		if 'QApplication' in globals() and QApplication.instance():
			msg_box = QMessageBox()
			msg_box.setIcon(QMessageBox.Icon.Critical)
			msg_box.setText("An error occurred during processing.")
			msg_box.setInformativeText(str(e))
			msg_box.setWindowTitle("Error")
			msg_box.exec()


if __name__ == '__main__':
	siril = s.SirilInterface()

	if len(sys.argv) == 1:
		run_gui()
	else:
		main_logic(sys.argv[1:])
