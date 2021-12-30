from PyQt5 import QtWidgets, uic
from prepSAS import Converter
import os, sys
import logging

logging.basicConfig(level=logging.INFO)

# Setup Path
if hasattr(sys, 'frozen') and hasattr(sys, '_MEIPASS'):
    package_dir = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
    os.chdir(package_dir)
else:
    package_dir = os.path.dirname(__file__)
PATH_TO_RESOURCES = os.path.join(package_dir, 'resources')


app = QtWidgets.QApplication([])


class MainWindow(QtWidgets.QMainWindow):
    TAB_DIR = 0
    TAB_FILE = 1

    def __init__(self):
        super(MainWindow, self).__init__()
        uic.loadUi(os.path.join(PATH_TO_RESOURCES, 'main.ui'), self)

        # Connect buttons
        self.btn_cal.clicked.connect(self.act_load_cal)
        self.btn_ini.clicked.connect(self.act_load_ini)

        self.btn_file_sas.clicked.connect(self.act_load_file_sas)
        self.btn_file_gps.clicked.connect(self.act_load_file_gps)
        self.btn_file_twr.clicked.connect(self.act_load_file_twr)
        self.btn_file_out.clicked.connect(self.act_load_file_out)

        self.btn_dir_in.clicked.connect(self.act_load_dir_in)
        self.btn_dir_out.clicked.connect(self.act_load_dir_out)

        self.btn_process.clicked.connect(self.act_process)

        self.show()

    def act_load_cal(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            caption='Select Satlantic Instrument File Definition (.cal, .tdf, .sip)', filter='(*.sip *.cal *.tdf)')
        self.line_cal.setText(filename)

    def act_load_ini(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            caption='Select pySAS Configuration File', filter='Ini File (*.ini)')
        self.line_ini.setText(filename)

    def act_load_file_sas(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            caption='Select pySAS Instrument Data', filter='Binary file (*.bin)')
        self.line_file_sas.setText(filename)

    def act_load_file_gps(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            caption='Select pySAS GPS Data', filter='GPS File (*.csv)')
        self.line_file_gps.setText(filename)

    def act_load_file_twr(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            caption='Select pySAS Tower Data', filter='Indexing Table File (*.csv)')
        self.line_file_twr.setText(filename)

    def act_load_file_out(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            caption='Select prepSAS Output File', filter='Output File (*.raw)')
        self.line_file_out.setText(filename)

    def act_load_dir_in(self):
        dirname = QtWidgets.QFileDialog.getExistingDirectory(
            caption='Select pySAS Data Directory')
        self.line_dir_in.setText(dirname)

    def act_load_dir_out(self):
        dirname = QtWidgets.QFileDialog.getExistingDirectory(
            caption='Select prepSAS Output Directory')
        self.line_dir_out.setText(dirname)

    def act_process(self):
        if not (self.line_cal.text() and self.line_ini.text()):
            msg = QtWidgets.QMessageBox()
            msg.setWindowTitle('prepSAS: Missing Configuration')
            msg.setIcon(QtWidgets.QMessageBox.Critical)
            msg.setText('Both the Satlantic Calibration and the pySAS configuration files are required')
            msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
            msg.exec()
            return
        try:
            c = Converter(self.line_cal.text(), self.line_ini.text())
        except Exception as e:
            msg = QtWidgets.QMessageBox()
            msg.setWindowTitle('prepSAS: Configuration')
            msg.setIcon(QtWidgets.QMessageBox.Critical)
            msg.setText('An error occurred while loading the configuration files.\n' + str(e))
            msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
            msg.exec()
            return

        if self.group_select_data.currentIndex() == self.TAB_FILE:
            if not (self.line_file_sas.text() and self.line_file_gps.text() and self.line_file_twr.text() and self.line_file_out.text()):
                msg = QtWidgets.QMessageBox()
                msg.setWindowTitle('prepSAS: Missing Files')
                msg.setIcon(QtWidgets.QMessageBox.Critical)
                msg.setText('Please specify the files you want to process. All fields must be filled.')
                msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
                msg.exec()
                return
            try:
                c.run(self.line_file_sas.text(), self.line_file_gps.text(), self.line_file_twr.text(), self.line_file_out.text())
            except Exception as e:
                msg = QtWidgets.QMessageBox()
                msg.setWindowTitle('prepSAS: Single File Processing')
                msg.setIcon(QtWidgets.QMessageBox.Critical)
                msg.setText('An error occurred while processing the files.\n' + str(e))
                msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
                msg.exec()
                return
        elif self.group_select_data.currentIndex() == self.TAB_DIR:
            if not (self.line_dir_in.text() and self.line_dir_out.text()):
                msg = QtWidgets.QMessageBox()
                msg.setWindowTitle('prepSAS: Missing Directories')
                msg.setIcon(QtWidgets.QMessageBox.Critical)
                msg.setText('Please specify the directory to process. All fields must be filled.')
                msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
                msg.exec()
                return
            mode = 'all' if self.rd_dir_mode_all.isChecked() else 'hour' if self.rd_dir_mode_hour.isChecked() else 'day'
            try:
                c.run_dir(self.line_dir_in.text(), self.line_dir_out.text(), mode=mode)
            except Exception as e:
                msg = QtWidgets.QMessageBox()
                msg.setWindowTitle('prepSAS: Directory Processing')
                msg.setIcon(QtWidgets.QMessageBox.Critical)
                msg.setText('An error occurred while processing the files in the directory.\n' + str(e))
                msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
                msg.exec()
                return

        msg = QtWidgets.QMessageBox()
        msg.setWindowTitle('prepSAS: Conversion Done')
        msg.setText('Selected data was converted for HyperInSpace.')
        msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
        msg.exec()


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()

    main_window = MainWindow()
    app.exec()


