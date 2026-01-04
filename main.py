# ... (st.balloons() satırından sonrası) ...
                        
                        # --- PUAN KARTI ---
                        st.markdown(f"""
                        <div style="
                            background-color: #f0fdf4; 
                            border: 2px solid #22c55e; 
                            border-radius: 10px; 
                            padding: 20px; 
                            text-align: center; 
                            margin-bottom: 20px;">
                            <h3 style="margin:0; color:#166534;">SINAV PUANI</h3>
                            <h1 style="margin:0; color:#15803d; font-size: 4rem;">{puan}</h1>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # --- SONUÇ DETAYLARI (Expander yerine Container) ---
                        # border=True kullanarak etrafına şık bir çerçeve ekledik
                        with st.container(border=True):
                            st.subheader("📝 Sonuç Detayları")
                            
                            st.markdown(f"**💡 Öğretmen Yorumu:**")
                            st.info(sonuc.get('ogretmen_yorumu'))
                            
                            st.markdown("**🗣️ Konuşma Metni (Transkript):**")
                            st.text_area("", transkript, height=150, disabled=True)
                            
                            st.markdown("**📊 Kriter Puanları (1-3 arası):**")
                            kp = sonuc.get("kriter_puanlari", {})
                            
                            # Tabloyu oluştur
                            df_puan = pd.DataFrame({
                                "Kriter": ["İçerik", "Düzen", "Dil", "Akıcılık"],
                                "Puan": [
                                    kp.get("konu_icerik", 0), 
                                    kp.get("duzen", 0), 
                                    kp.get("dil", 0), 
                                    kp.get("akicilik", 0)
                                ]
                            })
                            # Tabloyu index olmadan göster
                            st.table(df_puan.set_index('Kriter'))
