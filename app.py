"""
Streamlit UI for the Deal Desk swarm.

Run:
    pip install -r requirements.txt
    streamlit run app.py

Prerequisites (run once, in this directory):
    python setup_environment.py
    python create_specialists.py
    python upload_skills.py
    python create_coordinator.py
"""

from pathlib import Path

import streamlit as st

from deal_desk_runner import run_deal_desk_stream


SPECIALISTS = [
    "Pricing Specialist",
    "Legal Reviewer",
    "Technical Fit Specialist",
    "Competitive Intel Analyst",
]
DEFAULT_RFP = Path("synthetic-data/rfp-acme-corp.md")
UPLOAD_CACHE = Path("/tmp/uploaded_rfp.md")


st.set_page_config(page_title="Deal Desk — Specialist Swarm", layout="wide")
st.title("Deal Desk — Specialist Swarm")
st.caption(
    "Drop an RFP in. A senior-partner coordinator fans the work out to four "
    "specialists in parallel, then synthesises a branded proposal response."
)

with st.sidebar:
    st.header("RFP input")
    uploaded = st.file_uploader("Upload an RFP", type=["md", "txt"])
    use_default = st.checkbox(
        "Use Acme Corp sample RFP", value=uploaded is None
    )
    st.divider()
    run_clicked = st.button(
        "Run Deal Desk",
        type="primary",
        use_container_width=True,
        disabled=(uploaded is None and not use_default),
    )

st.subheader("Specialists")
cols = st.columns(len(SPECIALISTS))
status_slots: dict[str, "st.delta_generator.DeltaGenerator"] = {}
for col, name in zip(cols, SPECIALISTS):
    with col:
        status_slots[name] = st.empty()
        status_slots[name].info(f"**{name}**\n\nidle")

st.subheader("Event stream")
log_slot = st.empty()
log_slot.code("(waiting…)")

st.subheader("Coordinator output")
output_slot = st.empty()
output_slot.markdown("_The coordinator's synthesis will stream here._")

download_slot = st.container()


def _resolve_rfp_path() -> Path | None:
    if uploaded is not None:
        UPLOAD_CACHE.write_bytes(uploaded.getvalue())
        return UPLOAD_CACHE
    if use_default:
        return DEFAULT_RFP
    return None


if run_clicked:
    rfp_path = _resolve_rfp_path()
    if rfp_path is None:
        st.error("Upload an RFP or check the sample option.")
        st.stop()

    for name in SPECIALISTS:
        status_slots[name].info(f"**{name}**\n\nidle")

    log_lines: list[str] = []
    text_chunks: list[str] = []
    downloaded: list[Path] = []

    for kind, data in run_deal_desk_stream(rfp_path):
        if kind == "error":
            st.error(data)
            break
        elif kind == "info":
            log_lines.append(f"ℹ️  {data}")
        elif kind == "session_started":
            log_lines.append(f"🚀 session: {data}")
        elif kind == "thread_created":
            if data in status_slots:
                status_slots[data].warning(f"**{data}**\n\nspawned")
            log_lines.append(f"🟡 spawned: {data}")
        elif kind == "thread_running":
            if data in status_slots:
                status_slots[data].warning(f"**{data}**\n\nrunning…")
            log_lines.append(f"🔵 running: {data}")
        elif kind == "delegate":
            log_lines.append(f"➡️  delegate → {data}")
        elif kind == "reply_received":
            if data in status_slots:
                status_slots[data].success(f"**{data}**\n\nreplied ✓")
            log_lines.append(f"🟢 reply ← {data}")
        elif kind == "text":
            text_chunks.append(data)
            output_slot.markdown("".join(text_chunks))
        elif kind == "tool_use":
            log_lines.append(f"🔧 tool: {data}")
        elif kind == "file_downloaded":
            downloaded.append(data)
            log_lines.append(f"📄 saved: {data.name}")
        elif kind == "done":
            log_lines.append(f"✅ done — session {data}")

        log_slot.code("\n".join(log_lines[-30:]))

    if downloaded:
        with download_slot:
            st.success(f"Generated {len(downloaded)} deliverable(s).")
            for path in downloaded:
                with open(path, "rb") as fh:
                    st.download_button(
                        label=f"⬇  Download {path.name}",
                        data=fh.read(),
                        file_name=path.name,
                        key=f"dl-{path.name}",
                    )
