# ==================== app.py (完整版，固定高度视频组件) ====================
import sys, os, time, shutil, zipfile, tempfile, json, base64
from pathlib import Path
from io import BytesIO
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PORTABLE_ROOT = SCRIPT_DIR.parent.parent
BIN_PATH = PORTABLE_ROOT / "bin"
os.environ["PATH"] = str(BIN_PATH) + ";" + os.environ.get("PATH", "")

IS_CLOUD = os.environ.get("STREAMLIT_RUN_ID") is not None

from core.srt_parser import parse_srt
from core.cutter import cut_media, cut_text
from core.comparator import compare_duration, SEPARATOR_KEYWORDS
from core.git_manager import upload_file_to_github, download_file_from_github

def format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')

def video_component(clip_bytes, clip_name, uid):
    """固定高度 iframe (500px)，放大缩小切换，不动态调节高度"""
    b64 = base64.b64encode(clip_bytes).decode('utf-8')
    ext = clip_name.rsplit('.', 1)[-1].lower()
    if ext == 'mp4':
        mime = 'video/mp4'
    elif ext == 'mp3':
        mime = 'audio/mpeg'
    elif ext == 'wav':
        mime = 'audio/wav'
    else:
        mime = f'video/{ext}'

    html = f"""
    <div id="container_{uid}" style="display:flex; flex-direction:column; gap:8px; height:100%;">
        <video id="vid_{uid}" width="320" height="auto" controls>
            <source src="data:{mime};base64,{b64}" type="{mime}">
        </video>
        <div>
            <button id="btn_{uid}" onclick="toggleSize_{uid}()" style="padding:4px 14px; font-size:14px; border:1px solid #888; border-radius:5px; background:#f5f5f5; cursor:pointer;">🔍 放大</button>
        </div>
    </div>
    <script>
    var isLarge_{uid} = false;
    function toggleSize_{uid}() {{
        var vid = document.getElementById('vid_{uid}');
        var btn = document.getElementById('btn_{uid}');
        if (!isLarge_{uid}) {{
            // 放大：宽度填满容器
            vid.style.width = '100%';
            vid.style.maxWidth = '100%';
            btn.innerText = '🔍 缩小';
            isLarge_{uid} = true;
        }} else {{
            vid.style.width = '320px';
            vid.style.maxWidth = '320px';
            btn.innerText = '🔍 放大';
            isLarge_{uid} = false;
        }}
    }}
    </script>
    """
    return html

st.set_page_config(page_title="CTE 5-friends SRT 截取工具", layout="wide")
st.title("🎬 CTE 5-friends SRT 智能截取 + 比对 + 三列展示")

# 初始化 session_state
if 'output_dir' not in st.session_state:
    st.session_state.output_dir = SCRIPT_DIR / "output"
if 'cut_done' not in st.session_state:
    st.session_state.cut_done = False
if 'reviews' not in st.session_state:
    st.session_state.reviews = []
if 'deleted_log' not in st.session_state:
    st.session_state.deleted_log = []
if 'cut_progress' not in st.session_state:
    st.session_state.cut_progress = 0
if 'import_done' not in st.session_state:
    st.session_state.import_done = False
if 'delete_index' not in st.session_state:
    st.session_state.delete_index = None

# ===== 侧边栏 =====
st.sidebar.header("🔧 工具")
st.sidebar.subheader("📂 本地导入备份")
imported_zip = st.sidebar.file_uploader("选择 .zip 备份文件", type=["zip"], key="import_zip")
if imported_zip is not None and not st.session_state.import_done:
    try:
        with zipfile.ZipFile(BytesIO(imported_zip.getbuffer())) as zf:
            if 'manifest.json' not in zf.namelist():
                st.sidebar.error("备份文件缺少 manifest.json")
            else:
                manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
                reviews = []
                for item in manifest['items']:
                    clip_name = item['clip_name']
                    text_name = item['text_name']
                    clip_bytes = zf.read(f"clips/{clip_name}") if f"clips/{clip_name}" in zf.namelist() else None
                    text_bytes = zf.read(f"texts/{text_name}") if f"texts/{text_name}" in zf.namelist() else None
                    reviews.append({
                        'index': item['index'],
                        'text': item['text'],
                        'clip_name': clip_name,
                        'text_name': text_name,
                        'start_sec': item['start_sec'],
                        'end_sec': item['end_sec'],
                        'actual_duration': item.get('actual_duration', 0.0),
                        'clip_bytes': clip_bytes,
                        'text_bytes': text_bytes,
                    })
                st.session_state.reviews = reviews
                st.session_state.cut_done = True
                st.session_state.import_done = True
                st.sidebar.success(f"✅ 本地导入成功，共 {len(reviews)} 个片段")
                st.rerun()
    except Exception as e:
        st.sidebar.error(f"本地导入失败: {e}")
else:
    if imported_zip is None:
        st.session_state.import_done = False

st.sidebar.subheader("🌐 从 GitHub 导入备份")
with st.sidebar.expander("配置远程导入"):
    remote_token = st.text_input("GitHub Token", type="password", key="remote_token")
    remote_repo = st.text_input("仓库（如 user/repo）", key="remote_repo")
    remote_path = st.text_input("远程路径（含文件名）", value="data/backups/1.zip", key="remote_path")
    if st.button("📥 从 GitHub 导入"):
        if not remote_token or not remote_repo or not remote_path:
            st.error("请填写所有字段")
        else:
            try:
                zip_bytes = download_file_from_github(remote_token, remote_repo, remote_path)
                with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
                    if 'manifest.json' not in zf.namelist():
                        st.error("远程文件不是有效的备份 zip")
                    else:
                        manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
                        reviews = []
                        for item in manifest['items']:
                            clip_name = item['clip_name']
                            text_name = item['text_name']
                            clip_bytes = zf.read(f"clips/{clip_name}") if f"clips/{clip_name}" in zf.namelist() else None
                            text_bytes = zf.read(f"texts/{text_name}") if f"texts/{text_name}" in zf.namelist() else None
                            reviews.append({
                                'index': item['index'],
                                'text': item['text'],
                                'clip_name': clip_name,
                                'text_name': text_name,
                                'start_sec': item['start_sec'],
                                'end_sec': item['end_sec'],
                                'actual_duration': item.get('actual_duration', 0.0),
                                'clip_bytes': clip_bytes,
                                'text_bytes': text_bytes,
                            })
                        st.session_state.reviews = reviews
                        st.session_state.cut_done = True
                        st.session_state.import_done = False
                        st.success(f"✅ 远程导入成功，共 {len(reviews)} 个片段")
                        st.rerun()
            except Exception as e:
                st.error(f"远程导入失败: {e}")

st.sidebar.header("🔧 GitHub 自动上传备份")
enable_github = st.sidebar.checkbox("启用自动上传备份", value=False)
if enable_github:
    github_token = st.sidebar.text_input("上传 Token", type="password", key="upload_token")
    repo_full = st.sidebar.text_input("上传仓库（如 user/repo）", key="upload_repo")
    github_remote_path = st.sidebar.text_input("上传路径（含文件名）", value="data/backups/1.zip", key="upload_path")
    commit_msg = st.sidebar.text_input("提交信息", "Auto-upload backup zip from CTE 5-friends")

# ===== 主界面 =====
col1, col2 = st.columns(2)
with col1:
    video_file = st.file_uploader("选择视频/音频文件", type=["mp4","mkv","avi","mov","mp3","wav","flac"], key="video")
with col2:
    srt_file = st.file_uploader("选择 SRT 文件", type=["srt"], key="srt")

col3, col4, col5 = st.columns(3)
with col3:
    output_format = st.selectbox("输出格式", ["原格式","mp4","mkv","mp3","wav"], index=0)
with col4:
    threshold = st.number_input("比对阈值（秒）", min_value=0.1, max_value=3.0, value=0.5, step=0.1)
with col5:
    prefix = st.text_input("文件名前缀", value="Clip")

start_btn = st.button("▶ 开始截取并比对", type="primary", disabled=(video_file is None or srt_file is None))

if start_btn and video_file and srt_file:
    st.session_state.import_done = False
    st.session_state.cut_done = False
    st.session_state.reviews = []
    st.session_state.deleted_log = []
    st.session_state.cut_progress = 0
    st.session_state.delete_index = None

    progress_bar = st.progress(0)
    status_text = st.empty()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        video_path = tmpdir_path / video_file.name
        srt_path = tmpdir_path / srt_file.name
        with open(video_path, "wb") as f:
            f.write(video_file.getbuffer())
        with open(srt_path, "wb") as f:
            f.write(srt_file.getbuffer())

        try:
            srt_entries = parse_srt(srt_path)
            total = len(srt_entries)
            status_text.info(f"解析到 {total} 个 SRT 片段")
        except Exception as e:
            st.error(f"SRT 解析失败: {e}")
            st.stop()

        out_ext = output_format.lower()
        if out_ext == "原格式":
            out_ext = video_path.suffix[1:]
        is_audio = out_ext in ("mp3","wav")

        clips_dir = Path(tempfile.mkdtemp())
        texts_dir = Path(tempfile.mkdtemp())
        successful = []
        deleted = []

        def get_media_duration(path: Path) -> float:
            try:
                if not path.exists():
                    return -1.0
                import subprocess
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode != 0 or not result.stdout.strip():
                    return -1.0
                return float(result.stdout.strip())
            except Exception:
                return -1.0

        for idx, entry in enumerate(srt_entries):
            progress_value = (idx + 1) / total
            progress_bar.progress(progress_value)
            status_text.text(f"正在处理 {idx+1}/{total}：{entry['text'][:30]}...")

            clip_name = f"{prefix}_{idx+1:03d}.{out_ext}"
            clip_path = clips_dir / clip_name
            text_name = f"{prefix}_{idx+1:03d}.txt"
            text_path = texts_dir / text_name

            try:
                cut_media(video_path, clip_path, entry['start_sec'], entry['end_sec'], is_audio)
                cut_text(entry, text_path)
                actual_duration = get_media_duration(clip_path)
                expected_duration = entry['end_sec'] - entry['start_sec']

                if actual_duration < 0:
                    st.warning(f"⚠️ 无法获取 {clip_name} 时长，已保留")
                elif abs(actual_duration - expected_duration) > threshold:
                    clip_path.unlink(missing_ok=True)
                    text_path.unlink(missing_ok=True)
                    deleted.append({
                        'index': idx+1,
                        'text': entry['text'],
                        'expected': round(expected_duration, 3),
                        'actual': round(actual_duration, 3),
                        'diff': round(abs(actual_duration - expected_duration), 3)
                    })
                    st.session_state.deleted_log.append(
                        f"❌ 删除 {clip_name}：实际 {actual_duration:.3f}s，理论 {expected_duration:.3f}s，偏差 {abs(actual_duration-expected_duration):.3f}s（阈值 {threshold}s）"
                    )
                    continue

                successful.append({
                    'index': idx+1,
                    'text': entry['text'],
                    'clip_name': clip_name,
                    'text_name': text_name,
                    'clip_path': str(clip_path),
                    'text_path': str(text_path),
                    'start_sec': entry['start_sec'],
                    'end_sec': entry['end_sec'],
                    'actual_duration': actual_duration
                })
            except Exception as e:
                st.session_state.deleted_log.append(f"❌ 处理 {clip_name} 时出错: {e}")
                deleted.append({'index': idx+1, 'text': entry['text'], 'error': str(e)})

        progress_bar.progress(1.0)
        status_text.success(f"处理完成！成功 {len(successful)} 个，删除 {len(deleted)} 个")

        if st.session_state.deleted_log:
            with st.expander("📋 删除片段日志"):
                for log in st.session_state.deleted_log:
                    st.text(log)

        for succ in successful:
            cp = Path(succ['clip_path'])
            tp = Path(succ['text_path'])
            succ['clip_bytes'] = cp.read_bytes() if cp.exists() else None
            succ['text_bytes'] = tp.read_bytes() if tp.exists() else None
            del succ['clip_path']
            del succ['text_path']

        st.session_state.reviews = successful
        st.session_state.cut_done = True

        if enable_github and github_token and repo_full and github_remote_path:
            try:
                zip_buffer = BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    manifest = {
                        "version": 1,
                        "description": "CTE 5-friends backup",
                        "items": []
                    }
                    for entry in successful:
                        clip_name = entry['clip_name']
                        text_name = entry['text_name']
                        if entry['clip_bytes'] is not None:
                            zf.writestr(f"clips/{clip_name}", entry['clip_bytes'])
                        if entry['text_bytes'] is not None:
                            zf.writestr(f"texts/{text_name}", entry['text_bytes'])
                        manifest["items"].append({
                            "index": entry['index'],
                            "text": entry['text'],
                            "clip_name": clip_name,
                            "text_name": text_name,
                            "start_sec": entry['start_sec'],
                            "end_sec": entry['end_sec'],
                            "actual_duration": entry.get('actual_duration', 0.0)
                        })
                    zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
                zip_buffer.seek(0)
                upload_file_to_github(
                    token=github_token,
                    repo_full=repo_full,
                    remote_path=github_remote_path,
                    file_content=zip_buffer.read(),
                    commit_message=commit_msg
                )
                st.sidebar.success(f"✅ 备份已上传到 {repo_full}/{github_remote_path}")
            except Exception as e:
                st.sidebar.error(f"❌ 上传失败: {e}")

# ===== 三列展示 =====
if st.session_state.cut_done and st.session_state.reviews:
    st.markdown("---")
    st.subheader("📋 截取结果（三列展示）")

    if st.session_state.delete_index is not None:
        idx_to_del = st.session_state.delete_index
        if 0 <= idx_to_del < len(st.session_state.reviews):
            del st.session_state.reviews[idx_to_del]
        st.session_state.delete_index = None
        st.rerun()

    for i, entry in enumerate(st.session_state.reviews):
        col_a, col_b, col_d = st.columns([2.5, 3.5, 0.6])
        with col_a:
            st.markdown(f"**{entry['index']:03d}**  {entry['text'][:80]}...")
            safe_text_json = json.dumps(entry['text'])[:200]
            uid = f"tts_{entry['index']}_{i}"
            tts_html = f"""
            <button id="{uid}" onclick="speak_{uid}()" style="padding:4px 14px; font-size:14px; border:none; border-radius:4px; background-color:#2196F3; color:white; cursor:pointer;">🔊 朗读</button>
            <script>
            function speak_{uid}() {{
                try {{
                    if (!window.speechSynthesis) {{ return; }}
                    window.speechSynthesis.cancel();
                    var u = new SpeechSynthesisUtterance({safe_text_json});
                    u.lang = 'zh-CN'; u.rate = 0.9;
                    window.speechSynthesis.speak(u);
                }} catch(e) {{ console.error('TTS error:', e); }}
            }}
            </script>
            """
            components.html(tts_html, height=50)
        with col_b:
            if entry.get('clip_bytes') is not None:
                if not entry['clip_name'].endswith(('.mp3','.wav','.flac')):
                    vid_uid = f"vid_{entry['index']}_{i}"
                    html = video_component(entry['clip_bytes'], entry['clip_name'], vid_uid)
                    # 固定高度 500px，避免动态问题
                    components.html(html, height=500)
                else:
                    st.audio(entry['clip_bytes'])
                    st.caption(entry['clip_name'])
            else:
                st.warning("文件不可用")
        with col_d:
            if st.button("🗑️ 删除", key=f"delete_{i}"):
                st.session_state.delete_index = i
                st.rerun()
        st.markdown("---")

    if st.button("📦 导出为 1.zip（备份）"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            manifest = {
                "version": 1,
                "description": "CTE 5-friends backup",
                "items": []
            }
            for entry in st.session_state.reviews:
                clip_name = entry['clip_name']
                text_name = entry['text_name']
                if entry.get('clip_bytes') is not None:
                    zf.writestr(f"clips/{clip_name}", entry['clip_bytes'])
                if entry.get('text_bytes') is not None:
                    zf.writestr(f"texts/{text_name}", entry['text_bytes'])
                manifest["items"].append({
                    "index": entry['index'],
                    "text": entry['text'],
                    "clip_name": clip_name,
                    "text_name": text_name,
                    "start_sec": entry['start_sec'],
                    "end_sec": entry['end_sec'],
                    "actual_duration": entry.get('actual_duration', 0.0)
                })
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
        zip_buffer.seek(0)
        st.download_button(label="⬇️ 点击下载 1.zip", data=zip_buffer, file_name="1.zip", mime="application/zip", key="export_zip")