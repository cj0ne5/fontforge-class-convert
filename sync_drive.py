# Download each student's SVG folder from Google Drive, build a font from it with FontForge,
# and upload the timestamped font files back into that student's folder.
#
# Easiest: double-click sync_drive.command (sets up the venv on first run).
# Or from the venv:  `python sync_drive.py`            (all student folders)
#                    `python sync_drive.py "Jane Doe"` (only the named folders)
#                    `python sync_drive.py --force`    (rebuild even if nothing changed)
# Only new/modified SVGs are downloaded, and unchanged students are skipped.
# Needs credentials.json (Google OAuth "Desktop app" client) next to this script.

import io
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

ROOT_FOLDER_ID = '1h1umcjuhmo6el8FT2fR28gA_A9N_wtWz'
SCOPES = ['https://www.googleapis.com/auth/drive']
FOLDER_MIME = 'application/vnd.google-apps.folder'

HERE = Path(__file__).parent
CREDENTIALS = HERE / 'credentials.json'
TOKEN = HERE / 'token.json'
WORK_DIR = HERE / 'drive_sync'
MANIFEST = WORK_DIR / 'manifest.json' # per student folder: Drive modified times of downloaded SVGs
FONTFORGE = shutil.which('fontforge') or '/opt/homebrew/bin/fontforge'


def get_service():
	creds = None
	if TOKEN.exists():
		creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
	if not creds or not creds.valid:
		try:
			if creds and creds.expired and creds.refresh_token:
				creds.refresh(Request())
		except RefreshError:
			creds = None # e.g. "Testing" OAuth apps revoke sign-ins after 7 days; just sign in again
		if not creds or not creds.valid:
			if not CREDENTIALS.exists():
				sys.exit(f'Missing {CREDENTIALS.name} - see the setup steps for creating an OAuth client.')
			flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES)
			creds = flow.run_local_server(port=0)
		TOKEN.write_text(creds.to_json())
	return build('drive', 'v3', credentials=creds)


def list_children(service, folder_id):
	items, page_token = [], None
	while True:
		resp = service.files().list(
			q=f"'{folder_id}' in parents and trashed = false",
			fields='nextPageToken, files(id, name, mimeType, modifiedTime)',
			pageSize=1000,
			pageToken=page_token,
			supportsAllDrives=True,
			includeItemsFromAllDrives=True,
		).execute()
		items.extend(resp.get('files', []))
		page_token = resp.get('nextPageToken')
		if not page_token:
			return items


def safe_name(name):
	return re.sub(r'[/\\:]', '_', name).strip() or 'unnamed'


def list_svgs(service, folder_id, rel=''):
	"""List every .svg under folder_id (including subfolders) as {relative path: {id, modifiedTime}}."""
	found = {}
	for item in list_children(service, folder_id):
		path = rel + safe_name(item['name'])
		if item['mimeType'] == FOLDER_MIME:
			found.update(list_svgs(service, item['id'], path + '/'))
		elif item['name'].lower().endswith('.svg'):
			found[path] = {'id': item['id'], 'modifiedTime': item['modifiedTime']}
	return found


def download(service, file_id, dest):
	dest.parent.mkdir(parents=True, exist_ok=True)
	request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
	with io.FileIO(dest, 'wb') as fh:
		downloader = MediaIoBaseDownload(fh, request)
		done = False
		while not done:
			_, done = downloader.next_chunk()


def sync_svgs(service, folder_id, svg_dir, known):
	"""Make svg_dir match Drive, downloading only new/modified files. Returns (remote files, number changed)."""
	remote = list_svgs(service, folder_id)
	changed = 0
	for path, info in remote.items():
		if known.get(path) != info or not (svg_dir / path).exists():
			download(service, info['id'], svg_dir / path)
			changed += 1
	for path in set(known) - set(remote): # deleted or renamed in Drive
		(svg_dir / path).unlink(missing_ok=True)
		changed += 1
	return remote, changed


def upload(service, path, folder_id):
	media = MediaFileUpload(str(path), mimetype='application/octet-stream')
	service.files().create(
		body={'name': path.name, 'parents': [folder_id]},
		media_body=media,
		fields='id',
		supportsAllDrives=True,
	).execute()


def main():
	force = '--force' in sys.argv[1:]
	only = set(sys.argv[1:]) - {'--force'}
	service = get_service()
	WORK_DIR.mkdir(exist_ok=True)
	manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
	timestamp = datetime.now().strftime('%Y-%m-%d_%H%M')

	students = [f for f in list_children(service, ROOT_FOLDER_ID) if f['mimeType'] == FOLDER_MIME]
	if only:
		students = [f for f in students if f['name'] in only]
	students.sort(key=lambda f: f['name'])
	print(f'Found {len(students)} student folder(s)')

	results = []
	for student in students:
		name = safe_name(student['name'])
		print(f'\n=== {name} ===')
		student_dir = WORK_DIR / name
		svg_dir = student_dir / 'SVG'
		entry = manifest.get(student['id'], {'files': {}, 'built': False})
		if not svg_dir.exists():
			entry = {'files': {}, 'built': False}
		files, changed = sync_svgs(service, student['id'], svg_dir, entry['files'])
		count = len(files)
		print(f'{count} SVG file(s), {changed} changed since last run')
		entry['files'] = files
		if changed:
			entry['built'] = False
		manifest[student['id']] = entry
		MANIFEST.write_text(json.dumps(manifest, indent=1))
		if count == 0:
			results.append((name, 'no SVG files'))
			continue
		if entry['built'] and not force:
			results.append((name, 'unchanged, skipped'))
			continue

		output_base = student_dir / f'{name}_{timestamp}'
		proc = subprocess.run(
			[FONTFORGE, '-script', str(HERE / 'batch_import_svg.py'), str(svg_dir), str(output_base), name],
			capture_output=True, text=True,
		)
		log = (proc.stdout + proc.stderr).strip()
		for line in log.splitlines():
			if line.startswith(('SKIPPED', 'Imported')):
				print('  ' + line)
		otf = output_base.with_name(output_base.name + '.otf')
		if proc.returncode != 0 or not otf.exists():
			print(log)
			results.append((name, 'FONT BUILD FAILED'))
			continue

		for ext in ('.otf', '.sfd'):
			out = output_base.with_name(output_base.name + ext)
			if out.exists():
				upload(service, out, student['id'])
				print(f'Uploaded {out.name}')
		entry['built'] = True
		MANIFEST.write_text(json.dumps(manifest, indent=1))
		skipped = sum(1 for line in log.splitlines() if line.startswith('SKIPPED'))
		results.append((name, f'ok ({count - skipped} glyphs, {skipped} skipped)'))

	print('\n=== Summary ===')
	for name, status in results:
		print(f'{name}: {status}')


if __name__ == '__main__':
	main()
