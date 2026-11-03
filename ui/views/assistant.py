"""AI analytics assistant: answers from the data, draws a chart when the question is a comparison or trend."""
import streamlit as st

from ui import charts as UC
from ui import theme as T

SUGGESTIONS = ["Compare Sberbank with other banks at 10 cr across tenors", "What is the best rate for 10 cr for 90 days?",
               "Show how deposit size changes the rate at 90 days", "What share of tenors does Sberbank lead at 5 cr?"]


def _show(m, i):
    with st.chat_message(m["role"], avatar="🟢" if m["role"] == "assistant" else None):
        st.markdown(m["text"])
        if m["role"] != "assistant":
            return
        if m.get("chart"):
            st.plotly_chart(UC.render(m["chart"], 400), width="stretch", key=f"chat_chart_{i}")
            if m.get("note"):
                st.markdown(f'<div class="note"><b>What this shows:</b> {m["note"]}</div>', unsafe_allow_html=True)
        st.markdown(T.pill("Verified against data", "ok") if m["grounded"] else T.pill(f"Check figures: {m['unverified']}", "warn"), unsafe_allow_html=True)
        if m.get("steps"):
            with st.expander("How this was answered"):
                st.code("\n".join(m["steps"]), language=None)


def render(svc, has_data):
    st.markdown("#### Analytics assistant")
    st.caption("Ask in plain English. Answers come from the current dataset only; comparisons and trends are drawn as charts with a short explanation.")
    if not has_data:
        st.info("No data is available yet. Open **Data operations** and run the first refresh.")
        return
    chat = st.session_state.setdefault("chat", [])
    cols = st.columns(len(SUGGESTIONS))
    picked = next((q for c, q in zip(cols, SUGGESTIONS) if c.button(q, key="sg_" + q, width="stretch")), None)
    for i, m in enumerate(chat):
        _show(m, i)
    q = st.chat_input("Ask about Sberbank vs peer deposit rates…") or picked
    if q:
        chat.append(dict(role="user", text=q))
        with st.spinner("Analysing…"):
            a = svc.ask(q, include_stale=False)
        chat.append(dict(role="assistant", text=a.text, grounded=a.grounded, unverified=a.unverified, steps=a.steps, chart=a.chart, note=a.chart_note))
        st.rerun()
    if chat and st.button("Clear conversation", key="clr"):
        st.session_state.chat = []
        svc.memory.clear()
        st.rerun()
