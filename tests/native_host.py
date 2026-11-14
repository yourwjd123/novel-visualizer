"""Only launched by desktop_e2e.py; accepts dialogs on behalf of that test."""

import sys
from PySide6.QtWidgets import QApplication
from novelviz.desktop import Desktop, LocalPage
from novelviz.demo import seed_visual_demo
from novelviz.storage import Store

LocalPage.javaScriptConfirm = lambda self, origin, message: True
app = QApplication([])
app.setApplicationName("NovelVisualizerE2E")
app.setOrganizationName("NovelStudioTests")
store = Store(sys.argv[1])
seed_visual_demo(store)
window = Desktop(sys.argv[1])
window.resize(1440, 1000)
window.show()
sys.exit(app.exec())
