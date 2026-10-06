# One-time cleanup: move the timestamped .otf/.sfd files that sync_drive.py uploaded into Drive's trash.
# Only matches "<student folder>_YYYY-MM-DD_HHMM.otf/.sfd" in the top level of each student folder.
#
# `python cleanup_drive.py`        dry run: list what would be trashed
# `python cleanup_drive.py --yes`  actually move them to the trash (restorable from Drive's Trash for 30 days)

import re
import sys

from sync_drive import FOLDER_MIME, ROOT_FOLDER_ID, get_service, list_children, safe_name

apply = '--yes' in sys.argv[1:]
service = get_service()
students = sorted((f for f in list_children(service, ROOT_FOLDER_ID) if f['mimeType'] == FOLDER_MIME), key=lambda f: f['name'])

total = 0
for student in students:
	pattern = re.compile(re.escape(safe_name(student['name'])) + r'_\d{4}-\d{2}-\d{2}_\d{4}\.(otf|sfd)$')
	matches = sorted((f for f in list_children(service, student['id']) if pattern.match(f['name'])), key=lambda f: f['name'])
	if not matches:
		continue
	print(f'\n=== {student["name"]} ({len(matches)} file(s)) ===')
	for f in matches:
		print(f'  {f["name"]}')
		if apply:
			service.files().update(fileId=f['id'], body={'trashed': True}, supportsAllDrives=True).execute()
	total += len(matches)

print(f'\n{"Trashed" if apply else "Would trash"} {total} file(s) in {len(students)} student folder(s)')
if not apply and total:
	print('Run again with --yes to move them to the trash.')
