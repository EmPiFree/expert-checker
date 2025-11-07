# expert_checker_core.py
# Core logic refactored from expert-checker-reborn.py
# Provides functions callable from a web UI.

import requests
import geopy.distance
import json
import time

DEBUG = False

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
}

def get_article_id(url, timeout=10):
    webcode = url.split("/")[-1].split("-")[0]
    params = {'webcode': webcode, 'storeId': 'e_2879130'}
    r = requests.get('https://production.brntgs.expert.de/api/pricepds', params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return data.get("articleId")

def get_article_id_from_search(search_term, timeout=10):
    params = {'q': search_term, 'storeId': 'e_2879130'}
    r = requests.get('https://production.brntgs.expert.de/api/search/suggest', params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    try:
        product_data = r.json().get("articleSuggest", [])
        suggestions = []
        for product in product_data:
            article = product.get("article", {})
            articleId = article.get("articleId")
            link = article.get("link")
            title = article.get("seoPageTitle", "").split(" - bei expert kaufen")[0]
            url = ("https://www.expert.de" + link) if link else None
            suggestions.append((articleId, url, title))
        return suggestions
    except Exception:
        return []

def get_branches(local_backup_path=None, timeout=10):
    headers_local = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0',
    }
    params = {
        "lat": 0,
        "lng": 0,
        "maxResults": 500,
        "device": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/131.0",
        "source": "HTML5",
        "withWebsite": True,
        "conditions": {"storeFinderResultFilter": "ALL"}
    }
    cookies = {'fmarktcookie': 'e_2879130'}

    try:
        r = requests.post(
            'https://production.brntgs.expert.de/_api/storeFinder/searchStoresByGeoLocation',
            headers=headers_local,
            json=params,
            cookies=cookies,
            timeout=timeout
        )
        r.raise_for_status()
        branches = r.json()
    except Exception:
        if DEBUG:
            print("Filialabruf direkt von expert nicht möglich. Nutze lokales Backup.")
        if local_backup_path:
            with open(local_backup_path, 'r', encoding='utf-8') as f:
                branches = json.load(f)
        else:
            raise
    return branches

def get_branch_product_data(webcode, storeid, max_retries=5, timeout=10):
    headers_local = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
        'Accept': 'application/json',
        'Accept-Language': 'de,en-US;q=0.7,en;q=0.3',
    }
    params = {'webcode': webcode, 'storeId': storeid}
    retry_delay = 2
    for attempt in range(max_retries):
        try:
            r = requests.get('https://production.brntgs.expert.de/api/pricepds', headers=headers_local, params=params, timeout=timeout)
            if r.status_code == 429:
                if DEBUG:
                    print(f"Rate limit für {storeid}. Warte {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                if DEBUG:
                    print(f"Fehler bei Filiale {storeid}: {e}")
                raise
            time.sleep(retry_delay)
            retry_delay *= 2
            continue

def get_coordinates(plz, timeout=8):
    try:
        plz = plz.strip()
        if not plz.isdigit() or len(plz) != 5:
            if DEBUG:
                print(f"Ungültige PLZ: {plz}")
            return None
        r = requests.get(f"https://api.zippopotam.us/de/{plz}", timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
        place = data["places"][0]
        return (float(place["latitude"]), float(place["longitude"]))
    except Exception:
        return None

def get_discount(articleId, timeout=10):
    total_discount = 0
    r = requests.get("https://production.brntgs.expert.de/api/activePromotions", headers=headers, timeout=timeout)
    r.raise_for_status()
    promotions = r.json()
    seen_titles = set()
    for promotion in promotions:
        try:
            affectedArticles = promotion["orderModification"][0]["affectedArticles"]
            if articleId in affectedArticles:
                title = promotion.get("title", "")
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                discount = promotion["orderModification"][0]["discountRanges"][0]["discount"]
                total_discount += discount
        except KeyError:
            pass
    return total_discount

def get_distance(coords1, coords2):
    return int(round(geopy.distance.geodesic(coords1, coords2).km, 0))

def format_price(number, is_shipping=False, has_online_stock=False):
    if is_shipping and not has_online_stock:
        return ""
    if number == 0:
        return "0,00€"
    return f"{number:.2f}€".replace(".", ",")

def create_html_report_string(offers, product_title, webcode, discount, branches):
    best_new_price = None
    best_display_price = None
    for offer in offers:
        if offer['online_stock'] > 0:
            if offer['on_display']:
                if best_display_price is None or offer['total_price'] < best_display_price['total_price']:
                    best_display_price = offer
            else:
                if best_new_price is None or offer['total_price'] < best_new_price['total_price']:
                    best_new_price = offer

    # Build simplified/clean HTML (keeps original layout)
    html = []
    html.append(f"<html><head><meta charset='utf-8'><title>expert checker — {webcode}</title>")
    html.append("<style>body{font-family:Arial, sans-serif;background:#f5f5f5;padding:20px} .container{max-width:1200px;margin:0 auto} table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden} th,td{padding:12px 15px;text-align:left;border-bottom:1px solid #eee} th{background:#f8f9fa}</style></head><body><div class='container'>")
    html.append(f"<h1>expert checker reborn</h1><div><strong>{product_title} (Webcode: {webcode})</strong></div>")
    html.append(f"<div>Direktabzug: {format_price(discount) if discount>0 else '-'}</div>")
    if best_new_price:
        html.append(f"<p>Beste neu: {format_price(best_new_price['total_price'])} — <a href='{best_new_price['url']}'>{best_new_price['store_name']}</a></p>")
    if best_display_price:
        html.append(f"<p>Ausstellung: {format_price(best_display_price['total_price'])} — <a href='{best_display_price['url']}'>{best_display_price['store_name']}</a></p>")
    html.append("<h2>Angebote</h2><table><tr><th>Filiale</th><th>Preis</th><th>Versand</th><th>Gesamtpreis</th><th>Verfügbarkeit</th></tr>")
    for o in offers:
        if o['online_stock'] == 0:
            availability = f"Nur lokal verfügbar ({o['stock']}x)"
        else:
            availability = f"Online verfügbar ({o['online_stock']}x)"
            if o['stock']>0:
                availability += f"<br>Lokal verfügbar ({o['stock']}x)"
        display_class = " style='background:#fff3cd'" if o['on_display'] else ""
        html.append(f"<tr{display_class}><td><a href='{o['url']}'>{o['store_name']}</a></td><td>{format_price(o['price'])}</td><td>{format_price(o['shipping'], is_shipping=True, has_online_stock=o['online_stock']>0)}</td><td>{format_price(o['total_price'])}</td><td>{availability}</td></tr>")
    html.append("</table><h2>Alle Filialen</h2><table><tr><th>Filiale</th><th>Branch ID</th><th>Expert ID</th></tr>")
    for b in branches:
        try:
            html.append(f"<tr><td>{b['store']['name']} {b['store']['city']}</td><td>{b['store']['id']}</td><td>{b['store']['expId']}</td></tr>")
        except Exception:
            continue
    html.append("</table></div></body></html>")
    return "\n".join(html)

def process_branch_offer(branch, url, user_coordinates, only_online_offers, only_new_items, webcode):
    try:
        branch_id = branch["store"]["id"]
        expert_id = branch["store"]["expId"]
        branch_name = branch["store"]["name"]
        branch_city = branch["store"]["city"]
        branch_coordinates = (branch["store"]["latitude"], branch["store"]["longitude"])
        if branch_city not in branch_name:
            branch_name = f"{branch_name} {branch_city}"
        final_url = f"{url}?branch_id={branch_id}"
        product_data = get_branch_product_data(webcode, storeid=expert_id)
        item_is_used = product_data["price"]["itemOnDisplay"]["onDisplay"] if product_data.get("price", {}).get("itemOnDisplay") else False

        if not product_data.get("price", {}).get("bruttoPrice"):
            return None

        if only_online_offers and not product_data["price"].get("onlineStock", 0):
            return None

        if only_new_items and item_is_used:
            return None

        promotion_info = product_data.get("promotionPrice", {})
        price = round(float(promotion_info.get("checkoutPrice", product_data["price"].get("bruttoPrice", 0))), 2)
        if product_data["price"].get("onlineStock", 0) > 0:
            try:
                shipping = round(float(product_data["price"]["shipmentArray"][0]["shipmentBruttoPrice"]), 2)
            except Exception:
                shipping = 0
        else:
            shipping = 0
        total_price = round(price + shipping, 2)

        return {
            "url": final_url,
            "price": price,
            "shipping": shipping,
            "total_price": total_price,
            "store": expert_id,
            "store_name": branch_name,
            "stock": product_data["price"].get("storeStock", 0),
            "online_store": product_data["price"].get("onlineStore", False),
            "online_stock": product_data["price"].get("onlineStock", 0),
            "on_display": item_is_used,
            "coordinates": branch_coordinates,
        }
    except Exception:
        return None
