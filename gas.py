import threading
import serial
import time
import pymysql
import tkinter as tk
from tkinter import messagebox, ttk
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
import re

# =============================
# CONFIGURACIÓN
# =============================
class Config:
    # Email
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    EMAIL_USER = "CORREO AQUI"
    EMAIL_PASS = "CONTRASEÑA DE APLICACION"  # Configurar contraseña de aplicación
    MAX_CORREOS = 3
    
    # MySQL
    DB_HOST = "localhost"
    DB_PORT = 3306
    DB_USER = "root"
    DB_PASS = ""
    DB_NAME = "gas_alerta"
    
    # Serial
    SERIAL_PORT = "COM8" # Cambiar según el sistema
    SERIAL_BAUD = 115200
    
    # Umbrales
    UMBRAL_ANALOGICO = 2000
    TIEMPO_COOLDOWN = 30  # segundos entre alertas

# =============================
# VARIABLES GLOBALES
# =============================
class Estado:
    gas_detectado = False
    ultima_alerta = 0
    valor_sensor = 0
    ultima_lectura = None
    conectado_serial = False
    lock = threading.Lock()

# =============================
# VALIDACIONES
# =============================
def validar_email(email):
    """Valida formato de email"""
    patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(patron, email) is not None

# =============================
# BASE DE DATOS
# =============================
class BaseDatos:
    @staticmethod
    def conectar():
        try:
            conn = pymysql.connect(
                host=Config.DB_HOST,
                user=Config.DB_USER,
                password=Config.DB_PASS,
                database=Config.DB_NAME,
                port=Config.DB_PORT,
                connect_timeout=5
            )
            return conn
        except Exception as e:
            print(f"[ERROR] MySQL: {e}")
            return None

    @staticmethod
    def obtener_usuarios():
        conn = BaseDatos.conectar()
        if not conn:
            return []
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, correo, enviados 
                    FROM usuarios_alerta 
                    ORDER BY id DESC
                """)
                return cursor.fetchall()
        except Exception as e:
            print(f"[ERROR] Obtener usuarios: {e}")
            return []
        finally:
            conn.close()

    @staticmethod
    def registrar_usuario(correo):
        if not validar_email(correo):
            return False, "Formato de correo inválido"
        
        conn = BaseDatos.conectar()
        if not conn:
            return False, "No se pudo conectar a la base de datos"
        
        try:
            with conn.cursor() as cursor:
                # Verificar si ya existe
                cursor.execute("SELECT id FROM usuarios_alerta WHERE correo = %s", (correo,))
                if cursor.fetchone():
                    return False, "Este correo ya está registrado"
                
                cursor.execute("""
                    INSERT INTO usuarios_alerta (correo) 
                    VALUES (%s)
                """, (correo,))
            conn.commit()
            return True, "Correo registrado correctamente"
        except Exception as e:
            return False, f"Error: {str(e)}"
        finally:
            conn.close()

    @staticmethod
    def eliminar_usuario(user_id):
        conn = BaseDatos.conectar()
        if not conn:
            return False
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM usuarios_alerta WHERE id = %s", (user_id,))
            conn.commit()
            return True
        except Exception as e:
            print(f"[ERROR] Eliminar usuario: {e}")
            return False
        finally:
            conn.close()

    @staticmethod
    def incrementar_envio(user_id):
        conn = BaseDatos.conectar()
        if not conn:
            return
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE usuarios_alerta 
                    SET enviados = enviados + 1
                    WHERE id = %s
                """, (user_id,))
            conn.commit()
        except Exception as e:
            print(f"[ERROR] Incrementar envío: {e}")
        finally:
            conn.close()

    @staticmethod
    def reiniciar_contadores():
        conn = BaseDatos.conectar()
        if not conn:
            return False
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE usuarios_alerta SET enviados = 0")
            conn.commit()
            return True
        except Exception as e:
            print(f"[ERROR] Reiniciar contadores: {e}")
            return False
        finally:
            conn.close()

    @staticmethod
    def registrar_evento(tipo, valor_sensor):
        """Registra eventos - OPCIONAL: Requiere tabla adicional"""
        # Esta función está deshabilitada para usar solo la BD básica
        pass

# =============================
# SISTEMA DE ALERTAS
# =============================
class SistemaAlertas:
    @staticmethod
    def enviar_alertas():
        """Envía alertas por correo con control de cooldown"""
        tiempo_actual = time.time()
        
        # Verificar cooldown
        if tiempo_actual - Estado.ultima_alerta < Config.TIEMPO_COOLDOWN:
            print("[INFO] Cooldown activo, alerta no enviada")
            return
        
        usuarios = BaseDatos.obtener_usuarios()
        enviados = 0
        
        for user_id, correo, enviados_count in usuarios:
            if enviados_count >= Config.MAX_CORREOS:
                print(f"[INFO] {correo} alcanzó el límite de envíos")
                continue
            
            if SistemaAlertas.enviar_correo(correo, Estado.valor_sensor):
                BaseDatos.incrementar_envio(user_id)
                enviados += 1
        
        if enviados > 0:
            Estado.ultima_alerta = tiempo_actual
            print(f"[✓] {enviados} alertas enviadas")
        
        return enviados

    @staticmethod
    def enviar_correo(destinatario, valor_sensor):
        """Envía un correo individual"""
        if not Config.EMAIL_PASS:
            print("[ERROR] Contraseña de correo no configurada")
            return False
        
        try:
            fecha = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            
            cuerpo = f"""
            ⚠️ ALERTA DE DETECCIÓN DE GAS ⚠️
            
            Fecha y hora: {fecha}
            Valor del sensor: {valor_sensor}
            Dispositivo: ESP32 + MQ2
            
            Se ha detectado una concentración anormal de gas.
            Por favor, tome las precauciones necesarias.
            
            ---
            Sistema automático de alertas
            """
            
            msg = MIMEText(cuerpo)
            msg["Subject"] = "⚠ ALERTA DE GAS - ACCIÓN REQUERIDA"
            msg["From"] = Config.EMAIL_USER
            msg["To"] = destinatario
            
            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(Config.EMAIL_USER, Config.EMAIL_PASS)
                server.sendmail(Config.EMAIL_USER, destinatario, msg.as_string())
            
            print(f"[✓] Correo enviado a {destinatario}")
            return True
            
        except Exception as e:
            print(f"[ERROR] Envío fallido a {destinatario}: {e}")
            return False

    @staticmethod
    def enviar_alerta_async():
        """Envía alertas en un hilo separado"""
        hilo = threading.Thread(target=SistemaAlertas.enviar_alertas, daemon=True)
        hilo.start()

# =============================
# LECTURA SERIAL
# =============================
class LectorSerial:
    def __init__(self):
        self.serial = None
        self.buffer = ""
        self.intentos_reconexion = 0
        
    def conectar(self):
        """Intenta conectar con el ESP32"""
        try:
            self.serial = serial.Serial(
                Config.SERIAL_PORT, 
                Config.SERIAL_BAUD, 
                timeout=0.1
            )
            Estado.conectado_serial = True
            print(f"[✓] ESP32 conectado en {Config.SERIAL_PORT}")
            self.intentos_reconexion = 0
            return True
        except Exception as e:
            Estado.conectado_serial = False
            print(f"[ERROR] No se pudo conectar: {e}")
            return False
    
    def reconectar(self):
        """Intenta reconectar después de pérdida de conexión"""
        if self.intentos_reconexion < 5:
            self.intentos_reconexion += 1
            print(f"[INFO] Intentando reconectar ({self.intentos_reconexion}/5)...")
            time.sleep(2)
            return self.conectar()
        return False
    
    def procesar_linea(self, linea):
        """Procesa una línea recibida del ESP32"""
        try:
            # Formato: AO: 1332 | DO: 1
            if "AO:" in linea and "DO:" in linea:
                partes = linea.split("|")
                ao = int(partes[0].split("AO:")[1].strip())
                do = int(partes[1].split("DO:")[1].strip())
                
                with Estado.lock:
                    Estado.valor_sensor = ao
                    Estado.ultima_lectura = datetime.now()
                
                # Detectar gas
                if do == 1 or ao > Config.UMBRAL_ANALOGICO:
                    with Estado.lock:
                        if not Estado.gas_detectado:
                            Estado.gas_detectado = True
                            BaseDatos.registrar_evento("GAS_DETECTADO", ao)
                            SistemaAlertas.enviar_alerta_async()
                else:
                    with Estado.lock:
                        Estado.gas_detectado = False
                        
        except Exception as e:
            print(f"[ERROR] Procesar línea: {e}")
    
    def leer_continuo(self):
        """Bucle principal de lectura serial"""
        while True:
            if not Estado.conectado_serial:
                if not self.reconectar():
                    time.sleep(5)
                    continue
            
            try:
                if self.serial and self.serial.in_waiting:
                    data = self.serial.read(self.serial.in_waiting).decode(errors="ignore")
                    self.buffer += data
                    
                    while "\n" in self.buffer:
                        linea, self.buffer = self.buffer.split("\n", 1)
                        linea = linea.strip()
                        
                        if linea:
                            print(f"[ESP32] {linea}")
                            self.procesar_linea(linea)
                
                time.sleep(0.01)
                
            except serial.SerialException:
                print("[ERROR] Conexión serial perdida")
                Estado.conectado_serial = False
                if self.serial:
                    self.serial.close()
                    self.serial = None
            except Exception as e:
                print(f"[ERROR] Lectura serial: {e}")
                time.sleep(0.1)

# =============================
# INTERFAZ GRÁFICA MEJORADA
# =============================
class InterfazModerna:
    def __init__(self, root):
        self.root = root
        self.configurar_ventana()
        self.crear_widgets()
        self.iniciar_actualizacion()
    
    def configurar_ventana(self):
        """Configura la ventana principal"""
        self.root.title("🔥 Monitor de Gas MQ2 - ESP32")
        self.root.geometry("600x700")
        self.root.resizable(False, False)
        
        # Estilos
        style = ttk.Style()
        style.theme_use('clam')
        
        # Colores
        self.color_normal = "#2ecc71"
        self.color_alerta = "#e74c3c"
        self.color_fondo = "#ecf0f1"
        self.color_panel = "#ffffff"
        
        self.root.configure(bg=self.color_fondo)
    
    def crear_widgets(self):
        """Crea todos los widgets de la interfaz"""
        
        # ===== PANEL DE ESTADO =====
        frame_estado = tk.Frame(self.root, bg=self.color_panel, relief=tk.RAISED, bd=2)
        frame_estado.pack(pady=20, padx=20, fill=tk.X)
        
        # Título
        tk.Label(
            frame_estado, 
            text="ESTADO DEL SISTEMA",
            font=("Arial", 14, "bold"),
            bg=self.color_panel,
            fg="#34495e"
        ).pack(pady=10)
        
        # Indicador principal
        self.label_estado = tk.Label(
            frame_estado,
            text="● Sistema Inicializando...",
            font=("Arial", 20, "bold"),
            bg=self.color_panel,
            fg="#95a5a6"
        )
        self.label_estado.pack(pady=15)
        
        # Frame de información
        info_frame = tk.Frame(frame_estado, bg=self.color_panel)
        info_frame.pack(pady=10, padx=20, fill=tk.X)
        
        # Valor del sensor
        tk.Label(
            info_frame,
            text="Valor Sensor:",
            font=("Arial", 11),
            bg=self.color_panel,
            fg="#7f8c8d"
        ).grid(row=0, column=0, sticky=tk.W, pady=5)
        
        self.label_valor = tk.Label(
            info_frame,
            text="---",
            font=("Arial", 11, "bold"),
            bg=self.color_panel,
            fg="#34495e"
        )
        self.label_valor.grid(row=0, column=1, sticky=tk.W, pady=5, padx=20)
        
        # Conexión
        tk.Label(
            info_frame,
            text="Conexión:",
            font=("Arial", 11),
            bg=self.color_panel,
            fg="#7f8c8d"
        ).grid(row=1, column=0, sticky=tk.W, pady=5)
        
        self.label_conexion = tk.Label(
            info_frame,
            text="Desconectado",
            font=("Arial", 11, "bold"),
            bg=self.color_panel,
            fg="#e74c3c"
        )
        self.label_conexion.grid(row=1, column=1, sticky=tk.W, pady=5, padx=20)
        
        # Última lectura
        tk.Label(
            info_frame,
            text="Última lectura:",
            font=("Arial", 11),
            bg=self.color_panel,
            fg="#7f8c8d"
        ).grid(row=2, column=0, sticky=tk.W, pady=5)
        
        self.label_tiempo = tk.Label(
            info_frame,
            text="---",
            font=("Arial", 11),
            bg=self.color_panel,
            fg="#34495e"
        )
        self.label_tiempo.grid(row=2, column=1, sticky=tk.W, pady=5, padx=20)
        
        # ===== PANEL DE CONTROLES =====
        frame_controles = tk.Frame(self.root, bg=self.color_fondo)
        frame_controles.pack(pady=10, padx=20, fill=tk.X)
        
        # Botones principales
        btn_style = {"font": ("Arial", 11), "width": 18, "height": 2}
        
        tk.Button(
            frame_controles,
            text="📧 Registrar Correo",
            command=self.ventana_registrar,
            bg="#3498db",
            fg="white",
            activebackground="#2980b9",
            **btn_style
        ).grid(row=0, column=0, padx=5, pady=5)
        
        tk.Button(
            frame_controles,
            text="👥 Ver Usuarios",
            command=self.ventana_ver_usuarios,
            bg="#9b59b6",
            fg="white",
            activebackground="#8e44ad",
            **btn_style
        ).grid(row=0, column=1, padx=5, pady=5)
        
        tk.Button(
            frame_controles,
            text="🔄 Reiniciar Contadores",
            command=self.reiniciar_contadores,
            bg="#e67e22",
            fg="white",
            activebackground="#d35400",
            **btn_style
        ).grid(row=1, column=0, padx=5, pady=5)
        
        tk.Button(
            frame_controles,
            text="📊 Historial",
            command=self.ventana_historial,
            bg="#1abc9c",
            fg="white",
            activebackground="#16a085",
            **btn_style
        ).grid(row=1, column=1, padx=5, pady=5)
        
        # ===== PANEL DE ESTADÍSTICAS =====
        frame_stats = tk.LabelFrame(
            self.root,
            text="📈 Estadísticas",
            font=("Arial", 12, "bold"),
            bg=self.color_panel,
            fg="#34495e",
            relief=tk.RAISED,
            bd=2
        )
        frame_stats.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)
        
        stats_inner = tk.Frame(frame_stats, bg=self.color_panel)
        stats_inner.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        
        self.label_usuarios = tk.Label(
            stats_inner,
            text="Usuarios registrados: 0",
            font=("Arial", 11),
            bg=self.color_panel,
            anchor=tk.W
        )
        self.label_usuarios.pack(fill=tk.X, pady=5)
        
        self.label_alertas = tk.Label(
            stats_inner,
            text="Alertas enviadas hoy: 0",
            font=("Arial", 11),
            bg=self.color_panel,
            anchor=tk.W
        )
        self.label_alertas.pack(fill=tk.X, pady=5)
        
        # ===== PIE DE PÁGINA =====
        footer = tk.Label(
            self.root,
            text="Sistema de Monitoreo v2.0 | ESP32 + MQ2",
            font=("Arial", 9),
            bg=self.color_fondo,
            fg="#7f8c8d"
        )
        footer.pack(side=tk.BOTTOM, pady=10)
    
    def actualizar_interfaz(self):
        """Actualiza los elementos de la interfaz"""
        with Estado.lock:
            # Estado del gas
            if Estado.gas_detectado:
                self.label_estado.config(
                    text="⚠ GAS DETECTADO ⚠",
                    fg="white",
                    bg=self.color_alerta
                )
            else:
                self.label_estado.config(
                    text="✓ Sistema Normal",
                    fg="white",
                    bg=self.color_normal
                )
            
            # Valor del sensor
            self.label_valor.config(text=str(Estado.valor_sensor))
            
            # Conexión
            if Estado.conectado_serial:
                self.label_conexion.config(text="Conectado", fg=self.color_normal)
            else:
                self.label_conexion.config(text="Desconectado", fg=self.color_alerta)
            
            # Última lectura
            if Estado.ultima_lectura:
                tiempo_str = Estado.ultima_lectura.strftime("%H:%M:%S")
                self.label_tiempo.config(text=tiempo_str)
        
        # Estadísticas
        usuarios = BaseDatos.obtener_usuarios()
        self.label_usuarios.config(text=f"Usuarios registrados: {len(usuarios)}")
        
        total_alertas = sum(u[2] for u in usuarios)
        self.label_alertas.config(text=f"Alertas enviadas: {total_alertas}")
    
    def iniciar_actualizacion(self):
        """Inicia el ciclo de actualización automática"""
        self.actualizar_interfaz()
        self.root.after(150, self.iniciar_actualizacion)
    
    def ventana_registrar(self):
        """Ventana para registrar un nuevo usuario"""
        win = tk.Toplevel(self.root)
        win.title("Registrar Correo")
        win.geometry("400x200")
        win.resizable(False, False)
        win.configure(bg=self.color_panel)
        win.transient(self.root)
        win.grab_set()
        
        tk.Label(
            win,
            text="Ingrese el correo electrónico:",
            font=("Arial", 11),
            bg=self.color_panel
        ).pack(pady=20)
        
        entry = tk.Entry(win, width=35, font=("Arial", 11))
        entry.pack(pady=10)
        entry.focus()
        
        def guardar():
            correo = entry.get().strip()
            if not correo:
                messagebox.showwarning("Advertencia", "Ingrese un correo")
                return
            
            exito, mensaje = BaseDatos.registrar_usuario(correo)
            
            if exito:
                messagebox.showinfo("Éxito", mensaje)
                win.destroy()
            else:
                messagebox.showerror("Error", mensaje)
        
        frame_btn = tk.Frame(win, bg=self.color_panel)
        frame_btn.pack(pady=10)
        
        tk.Button(
            frame_btn,
            text="Guardar",
            command=guardar,
            bg="#2ecc71",
            fg="white",
            font=("Arial", 10),
            width=12
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            frame_btn,
            text="Cancelar",
            command=win.destroy,
            bg="#95a5a6",
            fg="white",
            font=("Arial", 10),
            width=12
        ).pack(side=tk.LEFT, padx=5)
        
        entry.bind('<Return>', lambda e: guardar())
    
    def ventana_ver_usuarios(self):
        """Ventana para ver usuarios registrados"""
        win = tk.Toplevel(self.root)
        win.title("Usuarios Registrados")
        win.geometry("700x400")
        win.configure(bg=self.color_panel)
        
        # Frame para la tabla
        frame_tabla = tk.Frame(win, bg=self.color_panel)
        frame_tabla.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(frame_tabla)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Treeview
        columns = ("id", "correo", "enviados")
        tree = ttk.Treeview(
            frame_tabla,
            columns=columns,
            show="headings",
            yscrollcommand=scrollbar.set
        )
        
        tree.heading("id", text="ID")
        tree.heading("correo", text="Correo Electrónico")
        tree.heading("enviados", text="Alertas Enviadas")
        
        tree.column("id", width=80, anchor=tk.CENTER)
        tree.column("correo", width=350)
        tree.column("enviados", width=150, anchor=tk.CENTER)
        
        tree.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=tree.yview)
        
        # Cargar datos
        usuarios = BaseDatos.obtener_usuarios()
        for user_id, correo, enviados in usuarios:
            tree.insert("", "end", values=(user_id, correo, enviados))
        
        # Botones
        frame_btn = tk.Frame(win, bg=self.color_panel)
        frame_btn.pack(pady=10)
        
        def eliminar_seleccionado():
            seleccion = tree.selection()
            if not seleccion:
                messagebox.showwarning("Advertencia", "Seleccione un usuario")
                return
            
            item = tree.item(seleccion[0])
            user_id = item['values'][0]
            correo = item['values'][1]
            
            if messagebox.askyesno("Confirmar", f"¿Eliminar a {correo}?"):
                if BaseDatos.eliminar_usuario(user_id):
                    tree.delete(seleccion[0])
                    messagebox.showinfo("Éxito", "Usuario eliminado")
        
        tk.Button(
            frame_btn,
            text="Eliminar Seleccionado",
            command=eliminar_seleccionado,
            bg="#e74c3c",
            fg="white",
            font=("Arial", 10),
            width=18
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            frame_btn,
            text="Actualizar",
            command=lambda: self.actualizar_tabla_usuarios(tree),
            bg="#3498db",
            fg="white",
            font=("Arial", 10),
            width=12
        ).pack(side=tk.LEFT, padx=5)
    
    def actualizar_tabla_usuarios(self, tree):
        """Actualiza la tabla de usuarios"""
        for item in tree.get_children():
            tree.delete(item)
        
        usuarios = BaseDatos.obtener_usuarios()
        for user_id, correo, enviados in usuarios:
            tree.insert("", "end", values=(user_id, correo, enviados))
    
    def ventana_historial(self):
        """Ventana para ver historial de eventos"""
        messagebox.showinfo(
            "Información",
            "El historial de eventos no está disponible con la estructura básica de BD.\n\n"
            "Esta función requiere tablas adicionales para almacenar eventos."
        )
    
    def reiniciar_contadores(self):
        """Reinicia los contadores de alertas"""
        if messagebox.askyesno(
            "Confirmar",
            "¿Reiniciar contadores de alertas enviadas?"
        ):
            if BaseDatos.reiniciar_contadores():
                messagebox.showinfo("Éxito", "Contadores reiniciados")
                self.actualizar_interfaz()
            else:
                messagebox.showerror("Error", "No se pudieron reiniciar contadores")

# =============================
# INICIO DEL SISTEMA
# =============================
def main():
    print("=" * 50)
    print(" Sistema de Monitoreo de Gas - Versión 2.0")
    print("=" * 50)
    
    # Reiniciar contadores al inicio
    print("[INFO] Reiniciando contadores...")
    BaseDatos.reiniciar_contadores()
    
    # Iniciar lector serial
    print("[INFO] Iniciando lector serial...")
    lector = LectorSerial()
    hilo_serial = threading.Thread(target=lector.leer_continuo, daemon=True)
    hilo_serial.start()
    
    # Iniciar interfaz
    print("[INFO] Iniciando interfaz gráfica...")
    root = tk.Tk()
    app = InterfazModerna(root)
    
    print("[✓] Sistema iniciado correctamente")
    print("=" * 50)
    
    root.mainloop()

if __name__ == "__main__":
    main()