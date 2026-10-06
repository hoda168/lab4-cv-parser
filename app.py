import json
import os
import tempfile

import requests
import streamlit as st
from langchain_community.document_loaders import PyPDFLoader


st.set_page_config(page_title="CV Parser", page_icon="📄", layout="wide")

st.title("HR Candidate Profile Parser")
st.write("Upload a text-based CV PDF and extract a structured candidate profile.")


def get_app_setting(name):
    """Read a value from Streamlit secrets, then fall back to an environment variable."""
    try:
        return st.secrets.get(name, os.getenv(name, ""))
    except Exception:
        # Local runs may not have a secrets.toml file.
        return os.getenv(name, "")


def extract_pdf_text(uploaded_file):
    """Save the uploaded PDF temporarily, load its pages, and return their text."""
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(uploaded_file.getvalue())
            temp_path = temp_file.name

        documents = PyPDFLoader(temp_path).load()
        return "\n".join(document.page_content for document in documents).strip()
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


with st.sidebar:
    st.header("API connection")

    api_url = st.text_input(
        "API URL",
        value=get_app_setting("CV_API_URL"),
        placeholder="https://your-ngrok-address.ngrok-free.dev/parse",
        help="Paste the public Parse endpoint URL printed by your Kaggle notebook.",
    )

    configured_api_token = get_app_setting("CV_API_TOKEN")
    if configured_api_token:
        # Keep a deployed secret on the server; do not send it to a browser widget.
        api_token = configured_api_token
        st.caption("Bearer token loaded from app settings.")
    else:
        # For local runs, the user can enter the token without saving it in source code.
        api_token = st.text_input(
            "Bearer token",
            type="password",
            help="Enter the same CV_API_TOKEN value saved in Kaggle Secrets.",
        )
        st.caption("The API token is not included in this app's source code.")


uploaded_pdf = st.file_uploader("Upload a candidate CV", type=["pdf"])
parse_clicked = st.button("Parse CV", type="primary")


if parse_clicked:
    st.session_state.pop("cv_result", None)

    if not api_url.strip():
        st.error("Enter the API URL in the sidebar.")
    elif not api_token.strip():
        st.error("Enter the Bearer token in the sidebar.")
    elif uploaded_pdf is None:
        st.error("Upload a PDF before clicking Parse CV.")
    else:
        try:
            with st.spinner("Extracting text from the PDF..."):
                cv_text = extract_pdf_text(uploaded_pdf)

            if not cv_text:
                st.error(
                    "No selectable text was found in this PDF. "
                    "It may be scanned; OCR is not included in this version."
                )
            else:
                endpoint = api_url.strip().rstrip("/")
                if not endpoint.endswith("/parse"):
                    endpoint += "/parse"

                headers = {"Authorization": f"Bearer {api_token.strip()}"}
                payload = {"text": cv_text}

                with st.spinner("Sending CV text to the Kaggle API..."):
                    response = requests.post(
                        endpoint,
                        headers=headers,
                        json=payload,
                        timeout=300,
                    )

                try:
                    result = response.json()
                except ValueError:
                    st.error("The API response was not valid JSON.")
                    st.code(response.text[:2000])
                else:
                    if not response.ok:
                        st.error(f"The API returned HTTP {response.status_code}.")
                        st.json(result)
                    elif not isinstance(result, dict):
                        st.error("The API returned JSON, but it was not an object.")
                        st.json(result)
                    elif "error" in result:
                        st.error(result["error"])
                    elif not any(
                        [
                            result.get("full_name"),
                            result.get("email"),
                            result.get("education"),
                            result.get("skills"),
                            result.get("experience"),
                        ]
                    ):
                        st.warning(
                            "No candidate information was found in the PDF. "
                            "It may be blank, scanned without readable text, "
                            "or not contain a candidate profile."
                        )
                    else:
                        st.session_state["cv_result"] = result

        except requests.exceptions.Timeout:
            st.error("The API took too long to respond. Try again while Kaggle is running.")
        except requests.exceptions.ConnectionError:
            st.error(
                "Could not reach the API. Check that the Kaggle server and ngrok tunnel "
                "are still running, and that the URL is correct."
            )
        except requests.exceptions.RequestException as error:
            st.error(f"The API request failed: {error}")
        except Exception as error:
            st.error(f"Could not read this PDF: {error}")


result = st.session_state.get("cv_result")

if result:
    st.subheader("Parsed candidate profile")

    name_col, email_col = st.columns(2)
    name_col.metric("Full name", result.get("full_name") or "Not found")
    email_col.metric("Email", result.get("email") or "Not found")

    st.markdown("### Education")
    education = result.get("education", [])
    if education:
        st.dataframe(education, hide_index=True)
    else:
        st.write("No education entries found.")

    st.markdown("### Skills")
    skills = result.get("skills", [])
    if skills:
        st.write(" · ".join(skills))
    else:
        st.write("No skills found.")

    st.markdown("### Experience")
    experience = result.get("experience", [])
    if experience:
        st.dataframe(experience, hide_index=True)
    else:
        st.write("No experience entries found.")

    st.markdown("### Raw JSON")
    st.json(result)

    json_bytes = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button(
        label="Download JSON",
        data=json_bytes,
        file_name="candidate_profile.json",
        mime="application/json",
    )
