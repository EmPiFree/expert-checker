# app.py
import streamlit as st
import expert_checker_core as core
import concurrent.futures
import streamlit.components.v1 as components
import time
import json
from io import StringIO

st.set_page_config(page_title="expert checker (web)", layout="wide")
st.title("expert checker — Web App")
st.markdown("Schnellsuche für expert.de — URL, Artikelnummer oder Suchbegriff eingeben.")

# Sidebar settings
with st.sidebar:
    st.header("Einstellungen")
    core.DEBUG = st.checkbox("DEBUG (Logs)", value=False)
    st.markdown("**Filters**")
    only_new_default = st.checkbox("Nur neue Artikel (keine Ausstellungsstücke)", value=True)
    only_online_default = st.checkbox("Nur Online-Angebote anzeigen", value=False)
    max_threads = st.slider("Max Threads (konservativ)", min_value=4, max_value=24, value=8, help="Weniger Threads reduziert Rate-Limit-Risiko.")
    st.markdown("---")
    st.markdown("Backup-Branchliste (optional)\n\nLade hier `expert_branches.json` hoch, wenn du eine lokale Kopie als Fallback nutzen willst.")
    uploaded = st.file_uploader("expert_branches.json", type=["json"])
    st.markdown("---")
    st.markdown("Session: Letzte Suchen (nur temporär, im Speicher)")

# Inputs row
col1, col2, col3 = st.columns([3,1,1])
with col1:
    term = st.text_input("Produkt-URL / Artikelnummer / Suchbegriff")
with col2:
    btn_search = st.button("Suchen")
with col3:
    st.write(" ")

# Extra UI toggles under inputs
cols = st.columns(3)
with cols[0]:
    only_new_items = st.checkbox("Ausstellungsstücke anzeigen?", value=not only_new_default)
with cols[1]:
    only_online_offers = st.checkbox("Lokale Angebote anzeigen?", value=not only_online_default)
with cols[2]:
    plz = st.text_input("PLZ (optional für lokale Suche)")

max_distance = None
if not only_online_offers:
    max_distance = st.number_input("Max Distanz (km, 0 = unbegrenzt)", min_value=0, value=100, step=10)

# Session history
if "history" not in st.session_state:
    st.session_state.history = []

if btn_search:
    if not term:
        st.error("Bitte URL/Artikelnummer/Suchbegriff eingeben.")
    else:
        st.info("Suche gestartet...")
        try:
            # If user uploaded branches file, write to temp path to pass to core
            local_backup_path = None
            if uploaded:
                try:
                    content = uploaded.read().decode("utf-8")
                    # Save to disk for core to read (in container)
                    with open("expert_branches.json", "w", encoding="utf-8") as f:
                        f.write(content)
                    local_backup_path = "expert_branches.json"
                    st.success("Backup-Branchliste hochgeladen und gespeichert.")
                except Exception as e:
                    st.warning("Upload failed; fallback to API only.")
                    local_backup_path = None

            start_time = time.time()

            # Determine articleId and URL
            articleId = None
            url = None

            # If it's digits-only, try API resolve by articleId
            if term.isdigit():
                try:
                    resp = core.get_branches(local_backup_path=local_backup_path)  # quick connectivity check
                except Exception:
                    pass
                # try to map articleId -> webcode / url via pricepds
                try:
                    r = core.get_branch_product_data  # just check function exists
                    # perform direct lookup using pricepds
                    import requests
                    rr = requests.get('https://production.brntgs.expert.de/api/pricepds',
                                      params={'articleId': term, 'storeId': 'e_2879130'},
                                      headers=core.headers, timeout=8)
                    if rr.status_code == 200:
                        d = rr.json()
                        webcode = d.get("webcode")
                        if webcode:
                            tr = requests.get(f"https://production.brntgs.expert.de/api/search/article?webcode={webcode}", headers=core.headers, timeout=8)
                            if tr.status_code == 200:
                                td = tr.json()
                                url = f"https://www.expert.de{td.get('link')}"
                                articleId = int(term)
                except Exception:
                    pass

            # If explicit expert URL provided
            if url is None and "www.expert.de" in term and ".html" in term:
                url = term.split(".html")[0] + ".html"
                try:
                    articleId = core.get_article_id(url)
                except Exception:
                    articleId = None

            # If still nothing and not numeric: use suggest API and let user pick
            if url is None and (not term.isdigit()):
                suggestions = core.get_article_id_from_search(term)
                if not suggestions:
                    st.warning("Keine Treffer in Suggest-API.")
                    st.stop()
                options = {f"{s[2]}": (s[0], s[1]) for s in suggestions if s[1]}
                choice = st.selectbox("Treffer auswählen:", list(options.keys()))
                if choice:
                    articleId, url = options[choice]

            if not url:
                st.error("Konnte Produkt-URL nicht bestimmen.")
                st.stop()

            # Coordinates
            user_coords = None
            if plz:
                user_coords = core.get_coordinates(plz)
                if user_coords is None:
                    st.warning("PLZ-Koordinaten konnten nicht ermittelt; es werden nur Online-Angebote berücksichtigt.")

            # Branches
            with st.spinner("Filialen abrufen..."):
                branches = core.get_branches(local_backup_path=local_backup_path)
            # Append online shop as before
            online_shop = {
                "store": {
                    "id": "e_2879130",
                    "expId": "2879130",
                    "city": "Onlineshop <",
                    "name": ">",
                    "latitude": 0,
                    "longitude": 0
                }
            }
            branches.append(online_shop)

            # Discount
            discount = 0
            if articleId:
                try:
                    discount = core.get_discount(articleId)
                except Exception:
                    discount = 0

            webcode = url.split("/")[-1].split("-")[0]

            # Query branches concurrently (conservative)
            st.info("Hole Angebote (siehe Status)...")
            results = []
            with st.spinner("Angebote abfragen..."):
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
                    futures = [executor.submit(core.process_branch_offer, b, url, user_coords, only_online_offers, only_new_items, webcode) for b in branches]
                    completed = 0
                    total = len(futures)
                    progress_bar = st.progress(0)
                    for f in concurrent.futures.as_completed(futures):
                        completed += 1
                        progress_bar.progress(int(completed/total*100))
                        try:
                            res = f.result()
                            if res:
                                # distance filter
                                if (not only_online_offers) and user_coords and res.get("coordinates"):
                                    dist = core.get_distance(user_coords, res["coordinates"])
                                    if max_distance and dist>max_distance>0:
                                        continue
                                results.append(res)
                        except Exception:
                            continue

            elapsed = time.time() - start_time
            if not results:
                st.warning("Keine Angebote gefunden.")
            else:
                # Sorting options
                sort_by = st.selectbox("Sortieren nach", ["Gesamtpreis (aufsteigend)", "Gesamtpreis (absteigend)", "Filiale (alphabetisch)"])
                if sort_by == "Gesamtpreis (aufsteigend)":
                    results = sorted(results, key=lambda x: x['total_price'])
                elif sort_by == "Gesamtpreis (absteigend)":
                    results = sorted(results, key=lambda x: x['total_price'], reverse=True)
                else:
                    results = sorted(results, key=lambda x: x['store_name'])

                # Build product title
                product_title = webcode
                try:
                    import requests
                    tresp = requests.get(f"https://production.brntgs.expert.de/api/search/article?webcode={webcode}", headers=core.headers, timeout=8)
                    if tresp.status_code == 200:
                        td = tresp.json()
                        product_title = td.get("seoPageTitle","").split(" - bei expert kaufen")[0] if td.get("seoPageTitle") else td.get("article", product_title)
                except Exception:
                    pass

                html = core.create_html_report_string(results, product_title, webcode, discount, branches)
                st.success(f"{len(results)} Angebote gefunden in {int(elapsed)}s.")
                # show embedded HTML
                components.html(html, height=700, scrolling=True)
                st.download_button("HTML herunterladen", data=html, file_name=f"expert_{webcode}.html", mime="text/html")

                # store in session history
                st.session_state.history.insert(0, {"term": term, "hits": len(results), "time": int(time.time())})
                if len(st.session_state.history) > 20:
                    st.session_state.history = st.session_state.history[:20]

                st.markdown("**Session-History:**")
                for h in st.session_state.history[:10]:
                    st.write(f"- `{h['term']}` — {h['hits']} Treffer — {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(h['time']))}")

        except Exception as e:
            st.exception(e)
