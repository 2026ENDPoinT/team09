"""Build an x64 Windows PDF/tutor portable trial on macOS, without changing the main app.

The private credentials file is intentionally included only when --include-credentials is supplied.
No user documents, recordings, caches or account state are copied.
"""
import argparse
import email
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parent.parent
PYTHON_VERSION='3.13.16'
PYTHON_SHA='97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297'
NAME='SYNESIS-Windows-PDF-Trial'


def download(url, path, digest=None):
    if not path.exists():
        temporary=path.with_suffix('.download')
        with urllib.request.urlopen(url,timeout=90) as source,temporary.open('wb') as target:shutil.copyfileobj(source,target)
        temporary.replace(path)
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest and actual!=digest:raise RuntimeError('Runtime checksum mismatch: '+path.name)
    return actual


def extract_wheels(wheels, site):
    dependencies=[]
    site.mkdir(parents=True,exist_ok=True)
    for wheel in sorted(wheels.glob('*.whl')):
        if not wheel.name.endswith(('win_amd64.whl','any.whl')):raise RuntimeError('Not a Windows x64 wheel: '+wheel.name)
        with zipfile.ZipFile(wheel) as archive:
            meta=email.message_from_bytes(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))))
            dependencies.append({'name':meta['Name'],'version':meta['Version'],'wheel':wheel.name,'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest()})
            for entry in archive.infolist():
                if entry.is_dir():continue
                pieces=Path(entry.filename).parts
                if any(p in ('..','') for p in pieces) or Path(entry.filename).is_absolute():raise RuntimeError('Unsafe wheel path')
                if pieces[0].endswith('.data'):
                    if pieces[1] in ('purelib','platlib'):pieces=pieces[2:]
                    elif pieces[1]=='scripts':continue  # The application invokes modules, never pip entry points.
                    else:pieces=('wheel-data',)+pieces
                target=site.joinpath(*pieces);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(entry))
    return dependencies


def write_windows(path,text,bom=False):
    path.write_bytes((b'\xef\xbb\xbf' if bom else b'')+text.replace('\r\n','\n').replace('\n','\r\n').encode('utf-8'))


def microsoft_runtime(cache):
    """Extract Microsoft's x64 CRT into the app; never install it on the build host."""
    folder=cache/'msvc-latest';metadata=folder/'metadata.json'
    if metadata.exists():return folder,json.loads(metadata.read_text())
    source='https://aka.ms/vc14/vc_redist.x64.exe';exe=cache/'VC_redist-latest.x64.exe'
    digest=download(source,exe);blob=exe.read_bytes();folder.mkdir(exist_ok=True);start=0;containers=[]
    while True:
        offset=blob.find(b'MSCF',start)
        if offset<0:break
        start=offset+4
        if offset+36>len(blob):continue
        size=struct.unpack_from('<I',blob,offset+8)[0]
        if not 36<=size<=len(blob)-offset:continue
        cabinet=folder/f'container-{len(containers)}.cab';cabinet.write_bytes(blob[offset:offset+size])
        target=folder/f'container-{len(containers)}';target.mkdir(exist_ok=True)
        subprocess.run(['bsdtar','-xf',str(cabinet),'-C',str(target)],check=True);containers.append(target)
    output=folder/'x64';output.mkdir(exist_ok=True)
    for container in containers:
        for item in container.iterdir():
            if item.read_bytes()[:4]!=b'MSCF':continue
            listing=subprocess.run(['bsdtar','-tf',str(item)],capture_output=True,text=True,check=True).stdout
            if 'msvcp140_1.dll_amd64' in listing:subprocess.run(['bsdtar','-xf',str(item),'-C',str(output)],check=True)
        manifest=container/'0'
        if manifest.exists() and manifest.read_bytes().startswith(b'\xef\xbb\xbf<?xml'):
            for node in ET.parse(manifest).getroot().iter():
                if node.tag.endswith('Payload') and node.attrib.get('FilePath')=='license.rtf':shutil.copy2(container/node.attrib['SourcePath'],folder/'LICENSE.rtf')
    if not (output/'msvcp140_1.dll_amd64').is_file():raise RuntimeError('Required Microsoft C++ runtime was not found.')
    result={'source':source,'sha256':digest,'dlls':[p.name.removesuffix('_amd64') for p in output.iterdir() if p.name.endswith('.dll_amd64')]}
    metadata.write_text(json.dumps(result,indent=2));return folder,result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--include-credentials',type=Path,required=True);args=parser.parse_args()
    destination=args.destination.resolve();destination.mkdir(parents=True,exist_ok=True)
    if any(p.name!='.DS_Store' for p in destination.iterdir()):raise RuntimeError('Destination must be empty; refusing to overwrite existing files.')
    credentials=args.include_credentials.resolve()
    if not credentials.is_file() or not credentials.read_bytes().strip():raise RuntimeError('Private credentials file is missing or empty.')
    cache=ROOT/'build/windows-trial-cache';cache.mkdir(parents=True,exist_ok=True)
    msvc,msvc_metadata=microsoft_runtime(cache)
    # Download only redistributable Windows binaries from their publishers.
    metadata=cache/'java-metadata.json'
    if metadata.exists():java=json.loads(metadata.read_text())
    else:
        query='https://api.azul.com/metadata/v1/zulu/packages/?java_version=21&os=windows&arch=x86&hw_bitness=64&archive_type=zip&java_package_type=jre&release_status=ga&availability_types=CA&latest=true'
        choices=json.load(urllib.request.urlopen(query,timeout=60));selected=next(x for x in choices if '-fx-' not in x['name'])
        java=json.load(urllib.request.urlopen('https://api.azul.com/metadata/v1/zulu/packages/'+selected['package_uuid'],timeout=60))
        metadata.write_text(json.dumps(java,indent=2))
    java_url=java['download_url'];java_zip=cache/java_url.rsplit('/',1)[1]
    java_hash=download(java_url,java_zip,java['sha256_hash'])
    python_zip=cache/f'python-{PYTHON_VERSION}-embed-amd64.zip'
    download(f'https://www.python.org/ftp/python/{PYTHON_VERSION}/{python_zip.name}',python_zip,PYTHON_SHA)
    wheels=cache/'wheels'
    if not (wheels/'requirements-resolved.json').exists():
        subprocess.run([sys.executable,'-m','pip','download','--dest',str(wheels),'--platform','win_amd64','--python-version','3.13','--implementation','cp','--abi','cp313','--only-binary=:all:','-r',str(ROOT/'requirements-pdf.txt')],check=True)
    dist=ROOT/'build/install/synesis-audio-poc/lib'
    if not (dist/'synesis-audio-poc.jar').is_file():raise RuntimeError('Run installDist before packaging.')
    jdk=ROOT/'.tools/jdk21/Contents/Home/bin';classes=ROOT/'build/windows-trial/classes';classes.mkdir(parents=True,exist_ok=True)
    sources=list((ROOT/'scripts/windows-trial/src').rglob('*.java'))
    subprocess.run([str(jdk/'javac'),'--release','21','-encoding','UTF-8','-cp',str(dist/'*'),'-d',str(classes),*[str(x) for x in sources]],check=True)
    app=destination/NAME;app.mkdir();(app/'lib').mkdir()
    for jar in dist.glob('*.jar'):
        if jar.name.startswith('sherpa-onnx'):continue
        shutil.copy2(jar,app/'lib'/jar.name)
    subprocess.run([str(jdk/'jar'),'--create','--file',str(app/'lib/windows-pdf-trial.jar'),'-C',str(classes),'.'],check=True)
    # Separate Windows runtime; no Mac venv binaries can be selected by PythonRuntime.
    runtime=app/'runtime/java';runtime.mkdir(parents=True)
    with zipfile.ZipFile(java_zip) as archive:
        prefix=archive.namelist()[0].split('/')[0]+'/'
        for entry in archive.infolist():
            if entry.is_dir():continue
            relative=entry.filename.removeprefix(prefix);target=runtime/relative
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(entry))
    python=app/'.venv-pdf/Scripts';python.mkdir(parents=True)
    with zipfile.ZipFile(python_zip) as archive:archive.extractall(python)
    dependencies=extract_wheels(wheels,python/'Lib/site-packages')
    (wheels/'requirements-resolved.json').write_text(json.dumps(dependencies,indent=2))
    # ONNX requires msvcp140_1 as well, which is not included by the Java runtime.
    # An app-local CRT avoids administrator access and system-wide installers.
    for dll in (msvc/'x64').glob('*.dll_amd64'):shutil.copy2(dll,python/dll.name.removesuffix('_amd64'))
    write_windows(python/'MICROSOFT-CRT-NOTICE.txt',
        'Microsoft Visual C++ v14 Runtime (x64), unmodified app-local runtime files.\n'
        'Publisher and copyright: Microsoft Corporation.\n'
        'License terms: https://aka.ms/VCRedistLicense\n'
        'Official download: '+msvc_metadata['source']+'\n'
        'Original installer SHA-256: '+msvc_metadata['sha256']+'\n')
    write_windows(python/'python313._pth','python313.zip\n.\nLib/site-packages\n../../scripts\nimport site\n')
    scripts=app/'scripts';scripts.mkdir()
    for source in (ROOT/'scripts').glob('pdf*.py'):shutil.copy2(source,scripts/source.name)
    shutil.copy2(ROOT/'scripts/synesis_paths.py',scripts/'synesis_paths.py')
    shutil.copy2(ROOT/'scripts/windows_parallel_check.py',scripts/'windows_parallel_check.py')
    shutil.copy2(ROOT/'scripts/windows-trial/windows_trial_check.py',scripts/'windows_trial_check.py')
    shutil.copytree(ROOT/'scripts/prompts',scripts/'prompts')
    (app/'config').mkdir();shutil.copyfile(credentials,app/'config/credentials.env');os.chmod(app/'config/credentials.env',0o600)
    write_windows(app/'launch.ps1',(ROOT/'scripts/windows-trial/launch.ps1').read_text(),bom=True)
    for name,option in [('SYNESIS-START.cmd',''),('SYNESIS-CHECK.cmd',' -CheckOnly')]:
        write_windows(app/name,'@echo off\nsetlocal DisableDelayedExpansion\npowershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0launch.ps1"'+option+'\n')
    guide='''SYNESIS · Windows PDF & AI멘토 시험판

실행 방법
1. ZIP 파일을 우클릭해 [모두 압축 풀기]를 선택해요.
2. 압축을 푼 폴더 안의 SYNESIS-START.cmd를 더블클릭해요.
3. [PDF 열기]로 공부할 PDF를 선택해요. 원문 준비 후 요약·개념 분석을 시작해요.
4. 위쪽 [AI멘토] 탭에서 PDF에 관해 질문해요.
5. 나중에 다시 실행하면 [내 문서]에서 저장된 PDF와 분석 결과를 열 수 있어요.

Java, Python, 별도 설치, 로그인은 필요하지 않아요. AI 분석·질문에는 인터넷이 필요해요.
Windows 10/11 64비트 Intel/AMD PC용이에요. ARM/Snapdragon PC와 32비트 Windows는 지원 대상으로 검증하지 않았어요.
실제 Windows PC에서의 최종 동작 확인은 아직 하지 못한 시험판이에요.
디지털 서명이 없는 개인 시험판이에요. Windows에서 실행 여부를 물으면 전달받은 파일이 맞는지 확인해 주세요.
회사·학교 관리 PC가 실행을 차단하면 관리자에게 문의해 주세요. 보안 프로그램을 끄지는 마세요.

공부할 때
- 처음 분석은 문서 크기에 따라 시간이 걸려요. 화면 아래에 진행 상태가 표시돼요.
- 완료된 요약·개념과 AI멘토 대화는 PC에 저장돼요. 저장된 결과를 다시 열 때는 새 분석을 요청하지 않으면 재사용해요.
- 스캔·복잡한 수식·표는 잘못 읽을 수 있으니 PDF 원문과 함께 확인해 주세요.
- PDF 분석, 요약, 개념정리, AI멘토만 제공해요. 플래너·녹음·계정 로그인·결제는 포함하지 않아요.
- 앱 안의 크레딧이 부족하면 상단 [시험 크레딧 추가]를 누를 수 있어요. 실제 결제 기능은 아니에요.

API 키와 비용
제공자의 API 키가 config 폴더에 포함돼 있어요. 별도로 입력할 필요가 없어요.
AI 분석·질문을 보내면 제공자의 API 계정에 실제 사용료가 발생해요. 시험 크레딧 추가로 실제 API 사용료가 없어지지는 않아요.
이 파일을 다른 사람에게 재전달하거나 공개 업로드하지 마세요. 시험 종료 후 제공자가 키를 폐기하거나 교체할 수 있어요.

저장 위치
PDF, 분석 결과, 대화, 화면 설정: %LOCALAPPDATA%\\SYNESIS-PDF-Trial
실행 폴더를 옮겨도 위 자료는 유지돼요. 앱 폴더 안의 lib/runtime/scripts/config/.venv-pdf 폴더는 이동·삭제하지 마세요.

실행이 안 될 때
1. ZIP 내부에서 직접 실행하지 말고, [모두 압축 풀기]를 했는지 확인해 주세요.
2. SYNESIS-CHECK.cmd를 실행해요. 이 검사는 AI 유료 요청을 보내지 않아요.
3. 문제가 계속되면 오류 창과 위 저장 위치 안의 .runtime/preflight.json, launch-날짜.log를 제공자에게 보내 주세요.
   config/credentials.env는 보내지 마세요. 문서·대화가 있는 library 폴더도 진단용으로 보낼 필요가 없어요.
4. 분석에만 실패한다면 인터넷, API 계정 잔액·모델 사용 권한을 제공자에게 확인해 주세요.
'''
    write_windows(app/'먼저 읽어주세요.txt',guide,bom=True)
    third_party={'java':{'vendor':'Azul Zulu OpenJDK','source':java_url,'sha256':java_hash,'license':'runtime/java/legal and DISCLAIMER/readme'},'python':{'version':PYTHON_VERSION,'source':f'https://www.python.org/downloads/release/python-31316/','sha256':PYTHON_SHA,'license':'.venv-pdf/Scripts/LICENSE.txt'},'microsoftAppLocalCrt':msvc_metadata,'pythonDependencies':dependencies,'javaDependencies':[x.name for x in (app/'lib').glob('*.jar')],'testStatus':'Cross-packaged on macOS; final Windows hardware run not yet performed. Offline preflight included.','credentialsIncluded':True,'userDocumentsIncluded':False}
    (app/'THIRD-PARTY-AND-BUILD.json').write_text(json.dumps(third_party,ensure_ascii=False,indent=2))
    write_windows(destination/'친구에게 보내는 방법.txt','친구에게 SYNESIS-Windows-PDF-Trial.zip 하나를 보내 주세요.\n친구는 압축을 모두 푼 뒤 SYNESIS-START.cmd를 더블클릭하면 돼요.\nAPI 키가 포함된 개인 시험판이므로 친구에게만 전달해 주세요. 실제 API 사용료는 키 소유자에게 청구돼요.\nWindows에서 최종 실행 확인은 아직 필요해요.\n',bom=True)
    archive=destination/(NAME+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        for path in sorted(app.rglob('*')):
            if path.is_file():output.write(path,path.relative_to(destination))
    print(json.dumps({'package':str(app),'zip':str(archive),'zipBytes':archive.stat().st_size,'privateCredentialsIncluded':True,'personalFilesIncluded':False},ensure_ascii=False))


if __name__=='__main__':main()
