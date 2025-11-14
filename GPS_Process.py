"""
**Processing script using sirilpy**

This script executes siril commands for background extraction, denoise and/or sharpening. It accepts arguments to define working directory, strenghts, amounts etc. It can run headlessly i.e. without the siril UI open, so it can run on a server or cloud instance.

With the CosmicClarity and GraXpert the executables must be installed and configured using their sirilpy scripts 1st.

The script can be started directly from the siril GUI, siril command line and can also be started from a ssf script using the 'pyscript' command i.e. pyscript GPS_Process.py. Such a ssf script can run the script several times i.e. to try different settings. The commands will process all fit(s) files found in the supplied working directory.

Example ssf script to run this script
---
requires 1.3.6
pyscript GPS_Process.py -d <workspace> -dc 0.5
pyscript GPS_Process.py -d <workspace> -sc 0.5 0.5 5
---

Processing for Siril
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
# Prototype sirilpy processing script
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
	config_dir = siril.get_siril_configdir()
	if os.path.isfile (f"{config_dir}/sirilcc_denoise.conf"):
		config_file_path = (f"{config_dir}/sirilcc_denoise.conf")
		with open(config_file_path, 'r') as file:
			executable_path = file.readline().strip()
			cc_input_dir = (executable_path.rsplit('/', 1)[0])+"/input"
			cc_output_dir = (executable_path.rsplit('/', 1)[0])+"/output"
	else:
		print("Executable not yet configured. It is recommended to use Seti Astro Cosmic Clarity v5.4 or higher.")
		sys.exit(1)

	os.chdir(cc_input_dir)
	for image in os.listdir():
		os.remove(image)
	os.chdir(workdir)

	for image in os.listdir():
		if image.endswith(".fits") or image.endswith(".fit"):
			siril.log(image)
			shutil.copy(image, cc_input_dir)			
			cmd = f"{executable_path} --denoise_mode {denoiseCC_mode} --denoise_strength {denoiseCC_strength} --separate_channels"
			process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)

			percent_re = re.compile(r"(\d+\.?\d*)" + "%")
			if process.stdout:
				for line in iter(process.stdout.readline, ''):
					line = line.strip()
					if not line:
						continue
					m = percent_re.search(line)
					if m:
						try:
							pct = float(m.group(1))
							siril.update_progress(f"Denoise:", pct / 100.0)
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
	config_dir = siril.get_siril_configdir()
	if os.path.isfile (f"{config_dir}/sirilcc_sharpen.conf"):
		config_file_path = (f"{config_dir}/sirilcc_sharpen.conf")
		with open(config_file_path, 'r') as file:
			executable_path = file.readline().strip()
			cc_input_dir = (executable_path.rsplit('/', 1)[0])+"/input"
			cc_output_dir = (executable_path.rsplit('/', 1)[0])+"/output"
	else:
		print("Executable not yet configured. It is recommended to use Seti Astro Cosmic Clarity v5.4 or higher.")
		sys.exit(1)

	os.chdir(cc_input_dir)
	for image in os.listdir():
		os.remove(image)
	os.chdir(workdir)		

	for image in os.listdir():
		if image.endswith(".fits") or image.endswith(".fit"):
			shutil.copy(image, cc_input_dir)

			cmd = f"{executable_path} --sharpening_mode '{sharpenCC_mode}' --nonstellar_strength {sharpenCC_non_stellar_strength} --stellar_amount {sharpenCC_stellar_amount} --nonstellar_amount  {sharpenCC_non_stellar_amount} --auto_detect_psf --sharpen_channels_separately"		
			process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)

			percent_re = re.compile(r"(\d+\.?\d*)" + "%")
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
def run_gui():
    if 'QApplication' not in globals():
        print("PyQt6 is not installed. Please install it to use the GUI.")
        print("pip install PyQt6")
        return

    class ProcessingDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Siril GPS_Processing")
            
            layout = QVBoxLayout(self)
            form_layout = QFormLayout()

            self.workdir_input = QLineEdit(os.getcwd())
            form_layout.addRow("Working Directory:", self.workdir_input)

            self.bkg_cb = QCheckBox("Siril Background Extraction")
            self.bkg_smooth = QLineEdit("0.5")
            self.bkg_smooth.setEnabled(False)
            self.bkg_cb.toggled.connect(self.bkg_smooth.setEnabled)
            form_layout.addRow(self.bkg_cb, self.bkg_smooth)

            self.bkg_grax_cb = QCheckBox("GraXpert Background Extraction")
            self.bkg_grax_smooth = QLineEdit("0.5")
            self.bkg_grax_smooth.setEnabled(False)
            self.bkg_grax_cb.toggled.connect(self.bkg_grax_smooth.setEnabled)
            form_layout.addRow(self.bkg_grax_cb, self.bkg_grax_smooth)

            self.denoise_cc_cb = QCheckBox("Cosmic Clarity Denoise")
            self.denoise_cc_mode = QLineEdit("luminance")
            self.denoise_cc_strength = QLineEdit("0.5")
            self.denoise_cc_mode.setEnabled(False)
            self.denoise_cc_strength.setEnabled(False)
            self.denoise_cc_cb.toggled.connect(self.denoise_cc_mode.setEnabled)
            self.denoise_cc_cb.toggled.connect(self.denoise_cc_strength.setEnabled)
            denoise_cc_layout = QHBoxLayout()
            denoise_cc_layout.addWidget(QLabel("Mode:"))
            denoise_cc_layout.addWidget(self.denoise_cc_mode)
            denoise_cc_layout.addWidget(QLabel("Strength:"))
            denoise_cc_layout.addWidget(self.denoise_cc_strength)
            form_layout.addRow(self.denoise_cc_cb, denoise_cc_layout)

            self.denoise_grax_cb = QCheckBox("GraXpert Denoise")
            self.denoise_grax_strength = QLineEdit("0.5")
            self.denoise_grax_strength.setEnabled(False)
            self.denoise_grax_cb.toggled.connect(self.denoise_grax_strength.setEnabled)
            form_layout.addRow(self.denoise_grax_cb, self.denoise_grax_strength)

            self.sharpen_cb = QCheckBox("Siril Sharpen (Deconvolution)")
            form_layout.addRow(self.sharpen_cb)

            self.sharpen_cc_cb = QCheckBox("Cosmic Clarity Sharpen")
            self.sharpen_cc_mode = QLineEdit("non_stellar")
            self.sharpen_cc_stellar_amount = QLineEdit("0.5")
            self.sharpen_cc_non_stellar_amount = QLineEdit("0.5")
            self.sharpen_cc_non_stellar_strength = QLineEdit("5")
            self.sharpen_cc_mode.setEnabled(False)
            self.sharpen_cc_stellar_amount.setEnabled(False)
            self.sharpen_cc_non_stellar_amount.setEnabled(False)
            self.sharpen_cc_non_stellar_strength.setEnabled(False)
            self.sharpen_cc_cb.toggled.connect(self.sharpen_cc_mode.setEnabled)
            self.sharpen_cc_cb.toggled.connect(self.sharpen_cc_stellar_amount.setEnabled)
            self.sharpen_cc_cb.toggled.connect(self.sharpen_cc_non_stellar_amount.setEnabled)
            self.sharpen_cc_cb.toggled.connect(self.sharpen_cc_non_stellar_strength.setEnabled)
            sharpen_cc_layout = QHBoxLayout()
            sharpen_cc_layout.addWidget(QLabel("Mode:"))
            sharpen_cc_layout.addWidget(self.sharpen_cc_mode)
            sharpen_cc_layout.addWidget(QLabel("Stellar Amount:"))
            sharpen_cc_layout.addWidget(self.sharpen_cc_stellar_amount)
            sharpen_cc_layout.addWidget(QLabel("Non-Stellar Amount:"))
            sharpen_cc_layout.addWidget(self.sharpen_cc_non_stellar_amount)
            sharpen_cc_layout.addWidget(QLabel("Non-Stellar Strength:"))
            sharpen_cc_layout.addWidget(self.sharpen_cc_non_stellar_strength)
            form_layout.addRow(self.sharpen_cc_cb, sharpen_cc_layout)

            self.sharpen_grax_cb = QCheckBox("GraXpert Sharpen")
            self.sharpen_grax_strength = QLineEdit("0.5")
            self.sharpen_grax_strength.setEnabled(False)
            self.sharpen_grax_cb.toggled.connect(self.sharpen_grax_strength.setEnabled)
            form_layout.addRow(self.sharpen_grax_cb, self.sharpen_grax_strength)

            layout.addLayout(form_layout)

            self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            self.button_box.accepted.connect(self.accept)
            self.button_box.rejected.connect(self.reject)
            layout.addWidget(self.button_box)

        def get_values(self):
            return {
                "workdir": self.workdir_input.text(),
                "bkg": self.bkg_smooth.text() if self.bkg_cb.isChecked() else None,
                "bkgGraX": self.bkg_grax_smooth.text() if self.bkg_grax_cb.isChecked() else None,
                "denoiseCC": [self.denoise_cc_mode.text(), self.denoise_cc_strength.text()] if self.denoise_cc_cb.isChecked() else None,
                "denoiseGraX": self.denoise_grax_strength.text() if self.denoise_grax_cb.isChecked() else None,
                "sharpen": self.sharpen_cb.isChecked(),
                "sharpenCC": [self.sharpen_cc_mode.text(), self.sharpen_cc_stellar_amount.text(), self.sharpen_cc_non_stellar_amount.text(), self.sharpen_cc_non_stellar_strength.text()] if self.sharpen_cc_cb.isChecked() else None,
                "sharpenGraX": self.sharpen_grax_strength.text() if self.sharpen_grax_cb.isChecked() else None,
            }

    app = QApplication.instance() or QApplication(sys.argv)
    dialog = ProcessingDialog()
    if dialog.exec():
        values = dialog.get_values()
        
        workdir = values["workdir"]
        
        try:
            siril.connect()
            siril.cmd("requires", "1.3.6")
            siril.log("Running processing from GUI")
            siril.cmd("cd", workdir)
            siril.cmd("set32bits")
            siril.cmd("setext", "fit")
        except Exception as e:
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setText("Siril connection error")
            msg_box.setInformativeText(str(e))
            msg_box.setWindowTitle("Error")
            msg_box.exec()
            return

        global smooth, bkgGraX, denoiseCC_mode, denoiseCC_strength, denoiseGraX, sharpenGraX, sharpenCC_mode, sharpenCC_stellar_amount, sharpenCC_non_stellar_amount, sharpenCC_non_stellar_strength
        
        if values["bkg"]:
            smooth = values["bkg"]
            bkg(workdir)

        if values["bkgGraX"]:
            bkgGraX = values["bkgGraX"]
            bkg_GraX(workdir)

        if values["sharpen"]:
            sharpen(workdir)

        if values["denoiseCC"]:
            denoiseCC_mode = values["denoiseCC"][0]
            denoiseCC_strength = values["denoiseCC"][1]
            denoise_CC(workdir)
            
        if values["denoiseGraX"]:
            denoiseGraX = values["denoiseGraX"]
            denoise_GraX(workdir)
                
        if values["sharpenGraX"]:
            sharpenGraX = values["sharpenGraX"]
            sharpen_GraX(workdir)
            
        if values["sharpenCC"]:
            sharpenCC_mode = values["sharpenCC"][0]
            sharpenCC_stellar_amount = values["sharpenCC"][1]
            sharpenCC_non_stellar_amount = values["sharpenCC"][2]	
            sharpenCC_non_stellar_strength = values["sharpenCC"][3]
            sharpen_CC(workdir)

        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setText("Processing finished.")
        msg_box.setWindowTitle("Success")
        msg_box.exec()

# ==============================================================================	
# Main execution
# ==============================================================================	

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-b","--bkg", nargs='+', help="siril background extraction, provide smoothing 0.0-1.0")
    parser.add_argument("-bg","--bkgGraX", nargs='+', help="siril background extraction, provide smoothing 0.0-1.0")
    parser.add_argument("-d","--workdir", nargs='+', help="set working directory")
    parser.add_argument("-dc","--denoiseCC", nargs='+', help="run CC denoise, provide mode (luminance,full,separate) and denoise strength 0.0-1.0")
    parser.add_argument("-dg","--denoiseGraX", nargs='+', help="denoise using GraXpert-AI, provide strength 0.0-1.0")
    parser.add_argument("-s","--sharpen", help="sharpen (deconvolution)" ,action="store_true")
    parser.add_argument("-sc","--sharpenCC", nargs='+', help="run CC sharpen, provide mode, stellar_amount and/or non_stellar_amount and non_stellar_strength")
    parser.add_argument("-sg","--sharpenGraX", nargs='+', help="sharpen (deconvolution) using GraXpert-AI, provide strength 0.0-1.0")

    siril = s.SirilInterface()
    VERSION = "0.1.0"

    if len(sys.argv) == 1:
        run_gui()
    else:
        args = parser.parse_args()
        try:
            siril.connect()
            siril.cmd("requires", "1.3.6")	
            siril.log("Running processing")
            workdir = args.workdir[0] if args.workdir else os.getcwd()	
            siril.cmd("cd", workdir)
            siril.cmd("set32bits")
            siril.cmd("setext", "fit")
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
            denoiseCC_mode = (args.denoiseCC[0])
            denoiseCC_strength = (args.denoiseCC[1])
            denoise_CC(workdir)
            
        if args.denoiseGraX:
            denoiseGraX = (args.denoiseGraX[0])
            denoise_GraX(workdir)
                
        if args.sharpenGraX:
            sharpenGraX = (args.sharpenGraX[0])
            sharpen_GraX(workdir)
            
        if args.sharpenCC:
            sharpenCC_mode = (args.sharpenCC[0])
            sharpenCC_stellar_amount = (args.sharpenCC[1])
            sharpenCC_non_stellar_amount = (args.sharpenCC[2])	
            sharpenCC_non_stellar_strength = (args.sharpenCC[3])
            sharpen_CC(workdir)
