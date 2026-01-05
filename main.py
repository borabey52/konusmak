import streamlit as st
import os
import json
import sqlite3
import pandas as pd
from datetime import datetime
import google.generativeai as genai
import time

# --- 1. AYARLAR ---
st.set_page_config(page_title="Konuşma Sınavı Sistemi", layout="wide", page_icon="🎓")
ADMIN_SIFRESI = "1234"  # <-- YÖNETİCİ ŞİFRESİ

# API Key Kontrolü
try:
    if "GOOGLE_API_KEY" in st.secrets:
        os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except Exception as e:
    pass

# --- 2. VERİTABANI VE DOSYA İŞLEMLERİ ---
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

def tum_sonuclari_getir():
    conn = sqlite3.connect('okul_sinav.db')
    df = pd.read_sql_query("SELECT * FROM sonuclar ORDER BY id DESC", conn)
    conn.close()
    return df

def konulari_getir():
    dosya_yolu = "konusma_konulari.xlsx"
    if not os.path.exists(dosya_yolu):
        data = {
            'Konu': ['Teknoloji Bağımlılığı', 'Doğa Sevgisi'],
            'Giriş': ['Bağımlılık tanımı', 'Doğanın önemi'],
            'Gelişme': ['Zararları', 'Faydaları'],
            'Sonuç': ['Çözüm', 'Özet']
        }
        pd.DataFrame(data).to_excel(dosya_yolu, index=False)
    try:
        df = pd.read_excel(dosya_yolu, engine='openpyxl')
        return {row['Konu']: {'Giriş': row['Giriş'], 'Gelişme': row['Gelişme'], 'Sonuç': row['Sonuç']} for i, row in df.iterrows()}
    except:
        return {}

def sesi_kalici_kaydet(audio_bytes, ad_soyad):
    klasor = "ses_kayitlari"
    if not os.path.exists(klasor): os.makedirs(klasor)
    tarih = datetime.now().strftime("%Y%m%d_%H%M%S")
    temiz_ad = "".join([c if c.isalnum() else "_" for c in ad_soyad]).strip("_")
    dosya_yolu = os.path.join(klasor, f"{temiz_ad}_{tarih}.wav")
    with open(dosya_yolu, "wb") as f: f.write(audio_bytes)
    return dosya_yolu

def sesi_analiz_et(audio_bytes, konu, detaylar, status_container):
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        status_container.update(label="Yapay Zeka Analiz Ediyor...", state="running")
        
        temp_file = "temp_ses.wav"
        with open(temp_file, "wb") as f: f.write(audio_bytes)
        
        audio_file = genai.upload_file(temp_file)
        while audio_file.state.name == "PROCESSING":
            time.sleep(0.5)
            audio_file = genai.get_file(audio_file.name)
            
        prompt = f"""
        Rol: Sen uzaman bir Türkçe Öğretmenisin. Öğrencinin yaptığı konuşmayı kriterlere göre değerlendir. Değerlendirme sırasında öğrencinin plana uymuş olmasına dikkat et. 
        Konu: {konu}. Plan: {detaylar}.
        Görev:
        1. Transkript çıkar.
        2. Kriterleri (İçerik, Düzen, Dil, Akıcılık) 1-3 puanla.
        3. Puan = (Toplam/12)*100.
        
        JSON Çıktısı:
        {{ "transkript": "...", "kriter_puanlari": {{"konu_icerik":0,"duzen":0,"dil":0,"akicilik":0}}, "yuzluk_sistem_puani":0, "ogretmen_yorumu":"..." }}
        """
        response = model.generate_content([audio_file, prompt])
        try: os.remove(temp_file) 
        except: pass
        
        return json.loads(response.text.replace("```json","").replace("```","").strip())
    except Exception as e:
        return {"yuzluk_sistem_puani": 0, "transkript": "Hata", "ogretmen_yorumu": str(e)}

# --- 3. ARAYÜZ ---
init_db()
if 'admin_logged_in' not in st.session_state: st.session_state['admin_logged_in'] = False

# --- SOL MENÜ (ŞİFRELİ GİRİŞ) ---
with st.sidebar:
    st.title("🔐 Yönetici Paneli")
    
    if not st.session_state['admin_logged_in']:
        sifre = st.text_input("Şifre:", type="password")
        if st.button("Giriş Yap"):
            if sifre == ADMIN_SIFRESI:
                st.session_state['admin_logged_in'] = True
                st.rerun()
            else:
                st.error("Hatalı Şifre!")
    else:
        st.success("Admin Girişi Yapıldı")
        secim = st.radio("Sayfa Seçiniz:", ["📝 Sınav Ekranı", "📂 Sonuç Arşivi"])
        if st.button("Çıkış Yap"):
            st.session_state['admin_logged_in'] = False
            st.rerun()

# --- MOD SEÇİMİNE GÖRE EKRAN ---

# MOD 1: SINAV EKRANI (İstediğiniz Özel Tasarım)
if not st.session_state['admin_logged_in'] or (st.session_state['admin_logged_in'] and secim == "📝 Sınav Ekranı"):
    
    # [1, 2, 1] Layout ile ortalama
    col_left, col_center, col_right = st.columns([1, 2, 1])
    
    with col_center:
        st.title("🎤 Dijital Konuşma Sınavı")
        st.markdown("---")
        
        # Form
        c1, c2 = st.columns(2)
        with c1: ad = st.text_input("Öğrenci Adı Soyadı")
        with c2: no = st.text_input("Sınıf / Numara")
        
        konular = konulari_getir()
        secilen_konu = st.selectbox("Konu Seçiniz:", list(konular.keys()), index=None)
        
        # PLAN KUTUCUKLARI (RENKLİ VE YAN YANA)
        if secilen_konu:
            detay = konular[secilen_konu]
            st.markdown(f"### 📋 {secilen_konu} - Konuşma Planı")
            k1, k2, k3 = st.columns(3)
            with k1: st.info(f"**1. GİRİŞ**\n\n{detay['Giriş']}")
            with k2: st.warning(f"**2. GELİŞME**\n\n{detay['Gelişme']}")
            with k3: st.success(f"**3. SONUÇ**\n\n{detay['Sonuç']}")

        st.markdown("<br>", unsafe_allow_html=True)

        # SABİT PUANLAMA TABLOSU (HTML)
        rubric_html = """
        <style>
            .rubric-table {width: 100%; border-collapse: collapse; font-size: 0.9em; margin-bottom: 20px;}
            .rubric-table th {background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 8px; text-align: left;}
            .rubric-table td {border: 1px solid #dee2e6; padding: 8px;}
        </style>
        <h4>⚖️ Puanlama Kriterleri</h4>
        <table class="rubric-table">
            <tr><th>Kriter</th><th>Açıklama</th><th>Puan (1-3)</th></tr>
            <tr><td><b>İçerik</b></td><td>Konuya hakimiyet ve plana uyum</td><td>1 - 3</td></tr>
            <tr><td><b>Düzen</b></td><td>Giriş, gelişme ve sonuç bütünlüğü</td><td>1 - 3</td></tr>
            <tr><td><b>Dil</b></td><td>Kelime zenginliği ve gramer</td><td>1 - 3</td></tr>
            <tr><td><b>Akıcılık</b></td><td>Telaffuz ve tonlama</td><td>1 - 3</td></tr>
        </table>
        """
        st.markdown(rubric_html, unsafe_allow_html=True)
        
        st.markdown("### 🎙️ Kaydı Başlat")
        ses = st.audio_input("Mikrofona Tıklayın")
        
        if ses and secilen_konu and st.button("Bitir ve Puanla", type="primary", use_container_width=True):
            if not ad: st.warning("İsim giriniz.")
            else:
                with st.status("Değerlendiriliyor...", expanded=True) as status:
                    ses_data = ses.getvalue()
                    yol = sesi_kalici_kaydet(ses_data, ad)
                    sonuc = sesi_analiz_et(ses_data, secilen_konu, konular[secilen_konu], status)
                    sonuc_kaydet(ad, no, secilen_konu, sonuc.get("transkript"), sonuc.get("yuzluk_sistem_puani"), sonuc, yol)
                    status.update(label="Tamamlandı", state="complete")
                    st.balloons()
                    
                    # BÜYÜK PUAN KARTI
                    st.markdown(f"""
                    <div style="background-color: #dcfce7; border: 2px solid #22c55e; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 20px;">
                        <h2 style="margin:0; color:#166534;">PUAN: {sonuc.get('yuzluk_sistem_puani')}</h2>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    with st.container(border=True):
                        st.info(f"**Yorum:** {sonuc.get('ogretmen_yorumu')}")
                        st.text_area("Metin", sonuc.get("transkript"), height=150)
                        kp = sonuc.get("kriter_puanlari", {})
                        st.table(pd.DataFrame({
                            "Kriter": ["İçerik", "Düzen", "Dil", "Akıcılık"],
                            "Puan": [kp.get("konu_icerik"), kp.get("duzen"), kp.get("dil"), kp.get("akicilik")]
                        }).set_index("Kriter"))
                        st.audio(yol)

# MOD 2: ADMİN ARŞİV EKRANI (Detaylı Görünüm)
elif st.session_state['admin_logged_in'] and secim == "📂 Sonuç Arşivi":
    st.title("📂 Arşiv ve Detaylar")
    df = tum_sonuclari_getir()
    
    if not df.empty:
        # İNTERAKTİF TABLO
        event = st.dataframe(
            df[["id", "ad_soyad", "sinif_no", "konu", "puan_100luk", "tarih"]],
            selection_mode="single-row",
            on_select="rerun",
            use_container_width=True,
            hide_index=True
        )
        
        if len(event.selection.rows) > 0:
            secilen = df.iloc[event.selection.rows[0]]
            st.divider()
            
            # 2 SÜTUNLU DETAY
            col_a, col_b = st.columns([1, 1])
            
            with col_a:
                st.subheader(f"👤 {secilen['ad_soyad']}")
                if os.path.exists(secilen['ses_yolu']):
                    st.audio(secilen['ses_yolu'])
                else:
                    st.error("Ses dosyası silinmiş.")
                st.text_area("Transkript", secilen['konusma_metni'], height=300, disabled=True)
                
            with col_b:
                st.markdown(f"# Puan: {secilen['puan_100luk']}")
                try:
                    detay = json.loads(secilen['detaylar'])
                    st.info(detay.get("ogretmen_yorumu"))
                    kp = detay.get("kriter_puanlari", {})
                    st.table(pd.DataFrame({
                        "Kriter": ["İçerik", "Düzen", "Dil", "Akıcılık"],
                        "Puan": [kp.get("konu_icerik"), kp.get("duzen"), kp.get("dil"), kp.get("akicilik")]
                    }).set_index("Kriter"))
                except:
                    st.error("Detay verisi okunamadı.")
    else:
        st.info("Kayıt yok.")
