"""
streamlit_app.py

A no-install, no-terminal web page for turning an events CSV into a
formatted PDF. Deploy this for free on Streamlit Community Cloud
(share.streamlit.io) and anyone with the link can use it from a browser.
"""

import base64
import io

import streamlit as st
from weasyprint import HTML

from events_core import build_full_html

st.set_page_config(page_title="Generatore PDF Eventi", page_icon="📅")

st.title("📅 Generatore PDF Eventi")
st.write(
    "Carica il file CSV degli eventi (esportato dal Google Form) e "
    "scarica il PDF pronto da pubblicare."
)

title_text = st.text_input(
    "Titolo del documento",
    value="Eventi Estivi Comune di Sambuca Pistoiese",
)

csv_file = st.file_uploader("File CSV degli eventi", type=["csv"])
logo_file = st.file_uploader(
    "Logo del Comune (opzionale)", type=["png", "jpg", "jpeg"]
)
fix_caps = st.checkbox(
    "Correggi automaticamente il testo scritto in MAIUSCOLO", value=True
)

if csv_file is not None:
    logo_data_uri = None
    if logo_file is not None:
        mime = "image/png" if logo_file.type == "image/png" else "image/jpeg"
        b64 = base64.b64encode(logo_file.read()).decode("ascii")
        logo_data_uri = f"data:{mime};base64,{b64}"

    try:
        full_html = build_full_html(
            csv_file.read(), title_text, logo_data_uri, fix_caps=fix_caps
        )
    except Exception as e:
        st.error(f"Errore nella lettura del CSV: {e}")
        st.stop()

    st.subheader("Anteprima")
    st.components.v1.html(full_html, height=500, scrolling=True)

    if st.button("Genera PDF", type="primary"):
        with st.spinner("Generazione PDF in corso..."):
            pdf_bytes = io.BytesIO()
            HTML(string=full_html).write_pdf(pdf_bytes)
            pdf_bytes.seek(0)
        st.success("PDF pronto!")
        st.download_button(
            "⬇️ Scarica il PDF",
            data=pdf_bytes,
            file_name="eventi.pdf",
            mime="application/pdf",
            type="primary",
        )
else:
    st.info("Carica un file CSV per iniziare.")
