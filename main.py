import streamlit as st
import os
import json
import sqlite3
import pandas as pd
from datetime import datetime
import google.generativeai as genai
import time

# --- 1. SAYFA VE API AYARLARI ---
st.set_page_config(page_title="Akıllı Konuşma Sınavı", layout="wide", page_icon="🎓")

try:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        os.environ["GOOGLE_API_KEY"] = api_key
        genai.configure(api_key=api_key)
    else:
        # Eğer secrets yoksa sidebar'dan girilmesine izin ver
        pass
except Exception as e:
    st.error(f"API Hatası: {e}")

# --- 2. VERİTABANI İŞLEMLERİ ---
def init_db():
    conn = sqlite3.connect('okul_sinav.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS sonuclar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_soyad TEXT,
            sinif_no TEXT,
            konu TEXT,
            konusma_metni TEXT,
            puan_100luk INTEGER,
            detaylar TEXT,
            ses_yolu TEXT,
            tarih DATETIME
        )
    ''')
    conn.commit()
    conn.close()

def sonuc_kaydet(ad, no, konu, metin, puan, detaylar, ses_path):
    conn = sqlite3.connect('okul_sinav.db')
    c = conn.cursor()
    c.execute("INSERT INTO sonuclar (ad_soyad, sinif_no, konu, konusma_metni, puan_100luk, detaylar, ses_yolu, tarih) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (ad, no, konu, metin, puan, json.dumps(detaylar, ensure_ascii=False), ses_path, datetime.now()))
    conn.commit()
    conn.close()

def sonuclari_listele():
    """Veritabanındaki son 50 sonucu getirir."""
    conn = sqlite3.connect('okul_sinav.db')
    try:
        df = pd.read_sql_query("SELECT ad_soyad, puan_100luk, konu, tarih FROM sonuclar ORDER BY id DESC LIMIT 50", conn)
        # Tarihi daha okunabilir yapalım
        df['tarih'] = pd.to_datetime(df['tarih']).dt.strftime('%d-%m %H:%M')
        df.columns = ["Ad Soyad", "Puan", "Konu", "Tarih"]
        return df
    except:
        return pd.DataFrame()
    finally:
        conn.close()

# --- 3. EXCEL VE SES KAYDI ---
def konulari_getir():
    dosya_yolu = "konusma_konulari.xlsx"
    if not os.path.exists(dosya_yolu):
        data = {
            'Konu': ['Teknoloji Bağımlılığı', 'Doğa Sevgisi'],
            'Giriş': ['Bağımlılık tanımı', 'Doğanın önemi'],
            'Gelişme': ['Zararları ve etkileri', 'İnsana faydaları'],
            'Sonuç': ['Çözüm yolları', 'Koruma yöntemleri']
        }
        pd.DataFrame(data).to_excel(dosya_yolu, index=False)
    
    try:
        df = pd.read_excel(dosya_yolu, engine='openpyxl')
        df.columns = df.columns.str.strip()
        konu_sozlugu = {}
        for index, row in df.iterrows():
            konu_sozlugu[row['Konu']] = {
                'Giriş': row['Giriş'], 'Gelişme': row['Gelişme'], 'Sonuç': row['Sonuç']
            }
        return konu_sozlugu
    except:
        return {}

def sesi_kalici_kaydet(audio_bytes, ad_soyad):
    klasor = "ses_kayitlari"
    if not os.path.exists(klasor):
        os.makedirs(klasor)
    tarih = datetime.now().strftime("%Y%m%d_%H%M%S")
    temiz_ad = "".join([c if c.isalnum() else "_" for c in ad_soyad]).strip("_")
    dosya_adi = f"{temiz_ad}_{tarih}.wav"
    dosya_yolu = os.path.join(klasor, dosya_adi)
    with open(dosya_yolu, "wb") as f:
        f.write(audio_bytes)
    return dosya_yolu

# --- 4. YAPAY ZEKA ---
def sesi_dogrudan_analiz_et(audio_bytes, konu, detaylar, status_container):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        status_container.update(label="Ses işleniyor...", state="running")
        temp_filename = "temp_ses.wav"
        with open(temp_filename, "wb") as f:
            f.write(audio_bytes)
        
        status_container.update(label="Analiz ediliyor...", state="running")
        audio_file = genai.upload_file(temp_filename)
        
        while audio_file.state.name == "PROCESSING":
            time.sleep(0.5)
            audio_file = genai.get_file(audio_file.name)
            
        status_container.update(label="Puan hesaplanıyor...", state="running")
        
        prompt = f"""
        Sen bir Türkçe öğretmenisin.
        SINAV KONUSU: {konu}
        BEKLENEN PLAN: {detaylar['Giriş']}, {detaylar['Gelişme']}, {detaylar['Sonuç']}
        
        GÖREV:
        1. Transkripti çıkar.
        2. Kriterlere 1-3 arası puan ver (3:İyi, 2:Orta, 1:Zayıf).
        3. Puanı hesapla: (Toplam Puan / 12) * 100.
        
        KRİTERLER: İçerik, Düzen, Dil, Akıcılık.
        
        JSON ÇIKTISI VER:
        {{
            "transkript": "...",
            "kriter_puanlari": {{ "konu_icerik": 0, "duzen": 0, "dil": 0, "akicilik": 0 }},
            "yuzluk_sistem_puani": 0,
            "ogretmen_yorumu": "..."
        }}
        """
        response = model.generate_content([audio_file, prompt])
        try:
            audio_file.delete()
            os.remove(temp_filename)
        except:
            pass
        return json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except Exception as e:
        return {"yuzluk_sistem_puani": 0, "transkript": "Hata", "ogretmen_yorumu": str(e)}

# --- 5. ARAYÜZ ---
init_db()

# CSS ile Sol Panel (Sidebar) Genişliğini Ayarlama
st.markdown(
    """
    <style>
    [data-testid="stSidebar"][aria-expanded="true"] > div:first-child {
        width: 350px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- SOL PANEL (GEÇMİŞ SONUÇLAR) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3135/3135715.png", width=80)
    st.title("Sınav Geçmişi")
    
    # API Key Kontrolü (Sidebar'da da görünür olsun)
    if "GOOGLE_API_KEY" not in os.environ:
        api_input = st.text_input("API Key Giriniz:", type="password")
        if api_input:
            os.environ["GOOGLE_API_KEY"] = api_input
            genai.configure(api_key=api_input)
            st.success("Key kaydedildi!")
    
    st.markdown("---")
    
    # Veritabanından verileri çek
    df_sonuclar = sonuclari_listele()
    if not df_sonuclar.empty:
        st.dataframe(df_sonuclar, hide_index=True, use_container_width=True)
    else:
        st.info("Henüz sınav kaydı yok.")
        
    st.markdown("---")
    st.caption("Veriler 'okul_sinav.db' dosyasında saklanır.")

# --- ANA EKRAN DÜZENİ ---
# Buradaki [1, 2, 1] oranı orta sütunu daraltarak daha derli toplu görünmesini sağlar
col_left, col_center, col_right = st.columns([1, 2, 1])

with col_center:
    st.title("🎤 Dijital Konuşma Sınavı")
    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1: ad_soyad = st.text_input("Öğrenci Adı Soyadı")
    with c2: sinif_no = st.text_input("Sınıf / Numara")
    
    st.markdown("<br>", unsafe_allow_html=True)

    konular = konulari_getir()
    secilen_konu = None
    
    if konular:
        secilen_konu = st.selectbox("Sınav Konusu:", list(konular.keys()), index=None, placeholder="Konu seçiniz...")
        
        if secilen_konu:
            detay = konular[secilen_konu]
            st.markdown(f"### 📋 {secilen_konu} - Plan")
            k1, k2, k3 = st.columns(3)
            with k1: st.info(f"**GİRİŞ**\n\n{detay['Giriş']}")
            with k2: st.warning(f"**GELİŞME**\n\n{detay['Gelişme']}")
            with k3: st.success(f"**SONUÇ**\n\n{detay['Sonuç']}")

    st.markdown("<br>", unsafe_allow_html=True)

    # Kriter Tablosu
    rubric_html = """
    <style>
        .rubric-table {width: 100%; border-collapse: collapse; font-size: 0.85em; margin-bottom: 20px;}
        .rubric-table th {background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 6px; text-align: left;}
        .rubric-table td {border: 1px solid #dee2e6; padding: 6px;}
    </style>
    <h4>⚖️ Puanlama Kriterleri</h4>
    <table class="rubric-table">
        <tr>
            <th>Kriter</th><th>Açıklama</th><th>Puan</th>
        </tr>
        <tr><td><b>1. İçerik</b></td><td>Konuya ve plana uyum</td><td>1-3</td></tr>
        <tr><td><b>2. Düzen</b></td><td>Giriş-Gelişme-Sonuç bütünlüğü</td><td>1-3</td></tr>
        <tr><td><b>3. Dil</b></td><td>Kelime ve gramer</td><td>1-3</td></tr>
        <tr><td><b>4. Akıcılık</b></td><td>Telaffuz ve tonlama</td><td>1-3</td></tr>
    </table>
    """
    st.markdown(rubric_html, unsafe_allow_html=True)

    st.markdown("### 🎙️ Kaydı Başlat")
    ses_kaydi = st.audio_input("Mikrofona tıklayın")

    if ses_kaydi and secilen_konu:
        if st.button("Bitir ve Puanla", type="primary", use_container_width=True):
            if not ad_soyad:
                st.warning("⚠️ Önce öğrenci adını giriniz.")
            else:
                with st.status("Değerlendiriliyor...", expanded=True) as status:
                    # Kayıt
                    audio_bytes = ses_kaydi.getvalue()
                    kayit_yolu = sesi_kalici_kaydet(audio_bytes, ad_soyad)
                    
                    # Analiz
                    sonuc = sesi_dogrudan_analiz_et(audio_bytes, secilen_konu, konular[secilen_konu], status)
                    
                    # Veritabanı
                    puan = sonuc.get("yuzluk_sistem_puani", 0)
                    transkript = sonuc.get("transkript", "")
                    sonuc_kaydet(ad_soyad, sinif_no, secilen_konu, transkript, puan, sonuc, kayit_yolu)
                    
                    status.update(label="Tamamlandı!", state="complete", expanded=False)
                    
                    # Sayfayı yenilemeden sidebar'ı güncellemek için rerun (isteğe bağlı)
                    # st.rerun() 
                    
                    st.balloons()

                    # Sonuç Gösterimi
                    st.markdown(f"""
                    <div style="background-color: #dcfce7; border: 2px solid #22c55e; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 20px;">
                        <h2 style="margin:0; color:#166534;">PUAN: {puan}</h2>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    with st.container(border=True):
                        st.subheader("Sonuç Detayları")
                        st.info(f"**Yorum:** {sonuc.get('ogretmen_yorumu')}")
                        st.text_area("Transkript", transkript, height=150)
                        
                        kp = sonuc.get("kriter_puanlari", {})
                        st.table(pd.DataFrame({
                            "Kriter": ["İçerik", "Düzen", "Dil", "Akıcılık"],
                            "Puan": [kp.get("konu_icerik",0), kp.get("duzen",0), kp.get("dil",0), kp.get("akicilik",0)]
                        }).set_index("Kriter"))
                        
                        st.audio(kayit_yolu)
