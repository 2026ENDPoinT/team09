"""Package the original SYNESIS app and animations, with a branded Windows native launcher.

Run with the PDF trial's already verified runtime as --runtime-base. No original UI source is changed.
Requires the Windows JDK jpackage module and x64 streaming wheels in the build cache.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parent.parent
CACHE=ROOT/'build/windows-trial-cache'
NAME='SYNESIS-Windows-Full-Trial'
EXPERIMENTAL_ASSISTANT_SCRIPTS=frozenset({
    'assistant_capabilities.py','assistant_engine.py','assistant_protocol_eager.py',
    'benchmark_assistant_engines.py','test_assistant_capabilities.py',
    'test_assistant_engine.py','test_benchmark_assistant_engines.py',
})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runtime-base',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);parser.add_argument('--include-credentials',type=Path)
    parser.add_argument('--name',default=NAME)
    args=parser.parse_args();base=args.runtime_base.resolve();destination=args.destination.resolve();name=args.name
    if Path(name).name!=name or name in ('.','..') or '\\' in name:raise RuntimeError('Package name must be a single folder name.')
    app=destination/name
    build_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    if app.exists() or (destination/(name+'.zip')).exists():raise RuntimeError('Refusing to overwrite an existing full trial.')
    if not (base/'.venv-pdf/Scripts/python.exe').is_file():raise RuntimeError('Verified runtime base is missing.')
    if args.include_credentials is not None and not args.include_credentials.is_file():raise RuntimeError('Private API configuration is missing.')
    spec=importlib.util.spec_from_file_location('pdf_packager',ROOT/'scripts/package-windows-pdf-trial.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    sys.path[:0]=[str(ROOT/'build/windows-full-trial/authoring-tools'),str(ROOT/'scripts/windows-full-trial')]
    from brand_launcher import brand
    app.mkdir(parents=True);(app/'app').mkdir()
    # Keep the original application's complete jar, fonts, artwork, UI and animation classes.
    dist=ROOT/'build/install/synesis-audio-poc/lib'
    for jar in dist.glob('*.jar'):
        if 'native-lib-osx' in jar.name:continue
        shutil.copy2(jar,app/'app'/jar.name)
    native=CACHE/'sherpa-onnx-native-lib-win-x64-v1.13.5.jar'
    if not zipfile.is_zipfile(native):raise RuntimeError('Windows audio JNI jar is missing.')
    shutil.copy2(native,app/'app'/native.name)
    classes=ROOT/'build/windows-full-trial/classes'
    if classes.exists():shutil.rmtree(classes)
    classes.mkdir(parents=True)
    jdk=ROOT/'.tools/jdk21/Contents/Home/bin'
    subprocess.run([str(jdk/'javac'),'--release','21','-encoding','UTF-8','-cp',str(dist/'*'),'-d',str(classes),
                    *map(str,(ROOT/'scripts/windows-full-trial/src').rglob('*.java'))],check=True)
    subprocess.run([str(jdk/'jar'),'--create','--file',str(app/'app/windows-full-trial.jar'),'-C',str(classes),'.'],check=True)
    shutil.copytree(base/'runtime/java',app/'runtime')
    shutil.copytree(base/'.venv-pdf',app/'.venv-pdf',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo'))
    site=app/'.venv-pdf/Scripts/Lib/site-packages'
    # Shared requests dependencies are already present. Replace protobuf 7 with the cloud STT-compatible 6 series.
    for stale in site.glob('protobuf-*.dist-info'):shutil.rmtree(stale)
    for stale in site.glob('certifi-*.dist-info'):shutil.rmtree(stale)
    if (site/'google/protobuf').exists():shutil.rmtree(site/'google/protobuf')
    audio_dependencies=helper.extract_wheels(CACHE/'streaming-wheels',site)
    # Each interpreter has its own standard library and DLLs; both share the verified PDF/STT packages.
    audio=app/'.venv/Scripts';audio.mkdir(parents=True)
    with zipfile.ZipFile(CACHE/'python-3.13.16-embed-amd64.zip') as z:z.extractall(audio)
    for dll in (CACHE/'msvc-latest/x64').glob('*.dll_amd64'):shutil.copy2(dll,audio/dll.name.removesuffix('_amd64'))
    helper.write_windows(audio/'python313._pth','python313.zip\n.\n../../.venv-pdf/Scripts/Lib/site-packages\n../../scripts\nimport site\n')
    scripts=app/'scripts';scripts.mkdir()
    for source in (ROOT/'scripts').glob('*.py'):
        if source.name in EXPERIMENTAL_ASSISTANT_SCRIPTS:continue
        if source.name.startswith(('test_','audit_','eval_','validate_','recheck_','smoke_','apply_','package-')):continue
        shutil.copy2(source,scripts/source.name)
    shutil.copytree(ROOT/'scripts/prompts',scripts/'prompts')
    # Preserve preflight checks; add full-app recording protocol imports without sending audio.
    check=(ROOT/'scripts/windows-trial/windows_trial_check.py').read_text()
    check=check.replace("/'runtime/java/bin'","/'runtime/bin'")
    check=check.replace("'pdf_pipeline','pdf_ai'):","'pdf_pipeline','pdf_ai','websocket','grpc','google.protobuf','lecture_stream','live_streams','soniox_billing'):")
    check=check.replace("'pdf_ai','websocket'","'pdf_ai','pdf_new_concept_ver99_study','pdf_visual_selection','pdf_study_hierarchy','pdf_tutor_cli','websocket'")
    if args.include_credentials is None:
        required="    if not credentials_file().is_file() or not api_key():\n        raise RuntimeError('The private API configuration is missing.')"
        optional="    if not credentials_file().is_file():\n        raise RuntimeError('The local API configuration template is missing.')\n    if not api_key():\n        print('AI key is not configured. Set config/credentials.env before using remote AI.',flush=True)"
        if required not in check:raise RuntimeError('Windows credential preflight changed; review the optional-config path.')
        check=check.replace(required,optional).replace("'private-config-present'","'config-file-present'")
    (scripts/'windows_trial_check.py').write_text(check)
    model=app/'models/speech-enhancement';model.mkdir(parents=True)
    shutil.copy2(CACHE/'gtcrn_simple.onnx',model/'gtcrn_simple.onnx')
    (app/'config').mkdir()
    if args.include_credentials is not None:shutil.copyfile(args.include_credentials,app/'config/credentials.env')
    else:helper.write_windows(app/'config/credentials.env','# Configure API keys locally before using remote AI or cloud transcription.\nOPENAI_API_KEY=\nSONIOX_API_KEY=\nDAGLO_API_TOKEN=\nGROQ_API_KEY=\n')
    os.chmod(app/'config/credentials.env',0o600)
    # The OpenJDK launcher loads the JVM in SYNESIS.exe itself: Explorer/taskbar keep the app's identity.
    branding=brand(CACHE/'jpackageapplauncherw.exe',ROOT/'src/main/resources/dev/synesis/poc/synesis-logo.png',app/'SYNESIS.exe',app/'SYNESIS.ico')
    cfg=['[Application]','app.mainclass=dev.synesis.poc.WindowsFullTrial','app.runtime=$ROOTDIR\\runtime']
    cfg.extend('app.classpath=$APPDIR\\'+jar.name for jar in sorted((app/'app').glob('*.jar')))
    cfg.extend(['','[JavaOptions]','java-options=-Djpackage.app-version=1.0.0',
                'java-options=-Dsynesis.buildId='+build_id,
                'java-options=-Dsynesis.appRoot=$ROOTDIR','java-options=-Dfile.encoding=UTF-8',
                'java-options=-Dstdout.encoding=UTF-8','java-options=-Dstderr.encoding=UTF-8'])
    helper.write_windows(app/'app/SYNESIS.cfg','\n'.join(cfg)+'\n')
    helper.write_windows(app/'SYNESIS-START.cmd','@echo off\nstart "" "%~dp0SYNESIS.exe"\n')
    helper.write_windows(app/'SYNESIS-CHECK.cmd','@echo off\nsetlocal DisableDelayedExpansion\npowershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0check.ps1"\n')
    helper.write_windows(app/'check.ps1',(ROOT/'scripts/windows-full-trial/check.ps1').read_text(),bom=True)
    guide='''SYNESIS · Windows 전체 화면 시험판

실행
1. ZIP 파일을 우클릭하고 [모두 압축 풀기]를 선택해요. 취소하지 말고 완료될 때까지 기다려 주세요.
2. 풀린 폴더 안의 SYNESIS.exe를 더블클릭해요. 앱 이름과 로고가 있는 실행 파일이에요.
3. 기존 시네시스 로그인 화면이 나오면 [Google로 시작하기]를 눌러요.
   이 버튼은 시험판의 앱 진입용이에요. 실제 Google 계정 인증이나 비밀번호 입력은 하지 않아요.
4. 내 문서에서 PDF를 추가하고 요약·개념정리·AI멘토를 사용할 수 있어요.

업데이트해서 실행할 때
기존 앱을 완전히 종료한 뒤, 이번 ZIP을 새 폴더에 모두 풀어 실행해요.
이전 폴더 위에 덮어쓰거나, 이전 버전의 실행 파일만 복사하지 마세요.
기존 전체판의 자료는 같은 사용자 저장 위치에서 이어서 사용해요.

Java나 Python을 따로 설치할 필요가 없어요. AI 기능에는 인터넷이 필요해요.
Windows 10/11 64비트 Intel/AMD PC용이고, ARM/Snapdragon PC는 검증하지 않았어요.
서명 없는 개인 시험판이므로 Windows가 실행 여부를 물을 수 있어요. 전달받은 파일이 맞는지 확인해 주세요.
회사·학교 PC에서 차단된다면 관리자에게 문의해 주세요. 보안 프로그램을 끄지는 마세요.

이번 파일은 PDF 전용 간소화판이 아니에요.
원래 앱의 로그인 화면, 진입 애니메이션, 내 문서, 폴더 관리, 플래너, PDF, 요약, 개념정리,
AI멘토, 퀴즈 화면, 강의록, 녹음 화면, 설정과 팝업을 그대로 포함해요.
일부 메뉴는 원래 앱에서도 준비 중이에요. 실제 Google 로그인·결제·알림 서비스가 추가된 것은 아니에요.
녹음·실시간 자막·소음 제거용 Windows 구성요소도 넣었지만 실제 Windows 마이크로 검증하지 못했어요.
로컬 Whisper 같은 추가 음성 모델은 포함하지 않아요. 관련 실험 기능은 작동하지 않을 수 있어요.
Mac과 Windows의 글자·입력·애니메이션 부드러움은 실제 PC에 따라 차이가 날 수 있어요.
로그인 전환·화면 효과·둥근 팝업·페이드 스크롤바와 정밀 스크롤 처리를 원본 코드 그대로 포함해요.
최신 PDF 도식·기사 보존과 분석 비용·처리량 개선도 포함해요.
이미 저장된 분석은 유지하고, 새로 분석할 때 개선된 분석 코드를 사용해요.
Windows의 긴 저장 경로 때문에 PDF 분석이 실패하던 문제를 수정했어요.
별도 시스템 설정 없이 긴 경로를 처리하고, 환경 검사에서는 320자 이상 결과·이미지 경로도 확인해요.
최신 N제 풀이 화면의 가독성 개선, 하단 고정 이동 버튼과 그림자, 문제집 목록 왕복 전환을 포함해요.
N제 생성은 다른 탭·PDF·홈 화면으로 이동해도 계속되고, 요청한 수에 부족하면 보충 생성을 진행해요.
문항 배분은 Fast 모드를 사용하고, 별도의 AI 독립 검증 호출 없이 생성한 문제를 표시해요.
기존의 제한된 병렬 호출과 공용 요청 슬롯을 그대로 사용해요. 환경 검사에는 4개 프로세스의
Windows 파일 잠금 동시성 검사가 추가됐어요. 진단은 AI 요청을 보내지 않아요.

API 키와 비용
요청에 따라 제공자의 API 키가 config 폴더에 포함돼 있어요. 별도 입력 없이 사용하도록 연결했어요.
AI 분석·질문·클라우드 음성 인식에는 실제 사용료가 발생하며 제공자의 API 계정에 청구돼요.
앱 안의 크레딧 충전은 모의 동작이고, 실제 API 청구를 없애거나 제한하는 기능은 아니에요.
키가 포함된 개인 시험판이므로 다른 사람에게 재전달하거나 공개 업로드하지 마세요.

자료 저장
이 전체판의 PDF, 플래너, 녹음, 대화, 설정은 %LOCALAPPDATA%\\SYNESIS-Windows-Trial 에 저장돼요.
이전 PDF 전용판과는 별도 저장 위치예요. 제공자의 개인 PDF·녹음·기존 계정 자료는 포함하지 않았어요.
앱 폴더를 옮겨도 위 자료는 남아요. app/runtime/scripts/config/.venv/.venv-pdf/models 폴더는 지우지 마세요.

문제가 있을 때
- ZIP 안에서 직접 실행하지 말고 모든 파일을 먼저 풀어 주세요.
- SYNESIS-CHECK.cmd로 기본 실행 환경을 검사할 수 있어요. 유료 AI 요청·녹음은 하지 않아요.
- 이미 앱이 켜져 있다면 닫은 뒤 검사해 주세요.
- 오류 화면과 위 자료 저장 위치의 .runtime 안 검사 기록을 제공자에게 보내 주세요.
- config/credentials.env나 개인 문서·녹음 폴더는 진단용으로 보낼 필요가 없어요.

현재 Mac에서 Windows용 파일을 구성하고 정적 검사·공통 코드 검사를 한 상태예요.
실제 Windows PC에서의 최종 실행 검증은 아직 필요해요.
'''
    if args.include_credentials is None:
        guide='''SYNESIS · Windows 전체 앱

실행 방법
1. ZIP을 [모두 압축 풀기]로 완전히 풀어요.
2. 풀린 폴더의 SYNESIS.exe를 실행해요.
3. 기존 로그인 화면에서 [Google로 시작하기]를 눌러 앱에 진입해요.
   현재 개발판의 진입 버튼이며 실제 Google 계정 인증은 수행하지 않아요.

Windows 10/11 64비트 Intel/AMD PC용이에요. Java와 Python은 함께 들어 있어요.
ARM/Snapdragon PC와 실제 Windows 하드웨어에서의 최종 실행은 검증하지 않았어요.
개인 개발판으로 코드 서명은 포함하지 않아요.

포함 기능
내 문서·폴더·PDF 불러오기, 플래너, PDF 보기, 강의 해설·개념 정리 생성,
AI멘토, 개인 학습 에이전트, N제 생성·풀이, 강의록, 녹음·실시간 자막·음성 보정,
설정과 기존 화면·애니메이션을 포함해요. 현재 로컬 프로젝트의 최신 변경을 반영했어요.
실제 Google 인증·결제·알림은 현재 앱의 개발 상태를 따르며, 크레딧 충전은 모의 동작이에요.
추가 로컬 음성 모델은 포함하지 않아요.

AI·음성 API 설정
API 키는 포함하지 않았어요. 본인의 키를 config/credentials.env에 입력해요.
OPENAI_API_KEY는 AI 기능, SONIOX_API_KEY 또는 DAGLO_API_TOKEN은 해당 실시간 자막 서비스에 사용해요.
인터넷 연결과 해당 서비스의 사용 권한이 필요하며 실제 API 사용료가 발생할 수 있어요.
앱의 모의 크레딧과 API 제공자의 실제 청구는 별개예요.

자료와 업데이트
개인 문서·녹음·계정 자료는 포함하지 않았어요.
자료는 %LOCALAPPDATA%\\SYNESIS-Windows-Trial 에 저장되며 기존 Windows 전체판 자료를 이어서 사용해요.
업데이트할 때 기존 앱을 종료하고 새 폴더에 이번 ZIP을 모두 풀어 실행해요.
기존 폴더에 실행 파일만 덮어쓰지 말고, app/runtime/scripts/config/.venv/.venv-pdf/models 폴더를 함께 유지해요.

실행 환경 검사
SYNESIS-CHECK.cmd는 기본 구성과 파일 무결성을 검사하며 유료 AI 요청이나 녹음은 하지 않아요.
API 키가 비어 있어도 실행 환경 검사 자체는 진행해요.
검사는 앱을 종료한 상태에서 실행해요. 기록은 자료 저장 위치의 .runtime 폴더에 남아요.
현재 macOS에서 Windows용 파일을 구성하고 정적 검사·공통 코드 검사를 수행한 배포본이에요.
'''
    helper.write_windows(app/'먼저 읽어주세요.txt',guide,bom=True)
    metadata=json.loads((base/'THIRD-PARTY-AND-BUILD.json').read_text())
    metadata.update({'edition':'original-full-application','buildId':build_id,
                     'builtAtUtc':datetime.now(timezone.utc).isoformat(),
                     'originalMainJarSha256':hashlib.sha256((app/'app/synesis-audio-poc.jar').read_bytes()).hexdigest(),
                     'nativeLauncher':branding,'streamingDependencies':audio_dependencies,'audioNativeJar':native.name,
                     'jdkLauncherSource':'https://github.com/openjdk/jdk21u/tree/master/src/jdk.jpackage',
                     'windowsJdkPackage':json.loads((CACHE/'windows-jdk-metadata.json').read_text()),
                     'noiseModelSource':'https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx',
                     'noiseModelSha256':hashlib.sha256((model/'gtcrn_simple.onnx').read_bytes()).hexdigest(),
                     'actualWindowsExecution':'not tested','personalFilesIncluded':False,
                     'credentialsIncluded':args.include_credentials is not None,
                     'windowsStoragePaths':'extended-unicode-prefix-and-short-exclusive-atomic-temp'})
    metadata['analysisScriptsSha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(scripts.glob('*.py'))}
    metadata['javaDependencies']=[p.name for p in sorted((app/'app').glob('*.jar'))]
    for dependency in audio_dependencies:
        metadata['pythonDependencies']=[p for p in metadata['pythonDependencies'] if p['name'].lower().replace('_','-')!=dependency['name'].lower().replace('_','-')]
        metadata['pythonDependencies'].append(dependency)
    (app/'THIRD-PARTY-AND-BUILD.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    helper.write_windows(app/'OPENJDK-LAUNCHER-NOTICE.txt','OpenJDK jpackage Windows application launcher, GPLv2 with Classpath exception.\nBranding resources changed to SYNESIS.\nSource: https://github.com/openjdk/jdk21u/tree/master/src/jdk.jpackage\nLicense: runtime/legal/java.base/LICENSE and ASSEMBLY_EXCEPTION\n')
    # The explicit check detects interrupted extraction without printing or hashing private keys.
    contents=[]
    for path in sorted(app.rglob('*')):
        if not path.is_file():continue
        relative=path.relative_to(app).as_posix()
        entry={'path':relative,'bytes':path.stat().st_size}
        if relative!='config/credentials.env':
            with path.open('rb') as source:entry['sha256']=hashlib.file_digest(source,'sha256').hexdigest()
        contents.append(entry)
    (app/'PACKAGE-CONTENTS.json').write_text(json.dumps({'buildId':build_id,'files':contents},indent=2),encoding='utf-8')
    archive=destination/(name+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(app.rglob('*')):
            if path.is_file():z.write(path,path.relative_to(destination))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise RuntimeError('Archive verification failed.')
    (destination/(name+'.sha256.txt')).write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
    config_note='API 키가 포함됐고 실제 AI 사용료는 키 소유자에게 청구돼요.' if args.include_credentials is not None else 'API 키는 포함하지 않았어요. AI 기능 사용 전 config/credentials.env를 설정해 주세요.'
    helper.write_windows(destination/'배포본 사용 방법.txt',name+'.zip 파일을 모두 푼 뒤 SYNESIS.exe를 실행해요.\n'+config_note+'\n실제 Windows PC에서의 최종 실행 확인은 아직 필요해요.\n',bom=True)
    print(json.dumps({'zip':str(archive),'zipBytes':archive.stat().st_size,'unpackedBytes':sum(p.stat().st_size for p in app.rglob('*') if p.is_file()),'originalUiPreserved':True,'credentialsIncluded':args.include_credentials is not None},ensure_ascii=False))


if __name__=='__main__':main()
