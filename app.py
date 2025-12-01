from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, make_response
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import hashlib
import os
import io
import base64
from functools import wraps
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.utils import ImageReader
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import json
from bson import json_util

app = Flask(__name__)
app.secret_key = 'clave_secreta_biblioteca_2024'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# Crear carpeta de uploads si no existe
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ----------------- CONEXIÓN A MONGODB -----------------
try:
    client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
    client.admin.command('ping') 

    db = client['libros']
    
    coleccion_libros = db['tipolibro']
    coleccion_usuarios = db['usuarios']
    coleccion_clientes = db['clientes']  
    coleccion_ventas = db['ventas']
    coleccion_pedidos = db['pedidos']  # Nueva colección para seguimiento
    coleccion_cancelaciones = db['cancelaciones']  # Nueva colección para cancelaciones

    print("Conexión exitosa a MongoDB.")

except Exception as e:
    print(f"ERROR: No se pudo conectar a MongoDB. Detalle: {e}")

# ----------------- FUNCIONES AUXILIARES -----------------
def encriptar_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_id' not in session:
            flash('Por favor inicia sesión como administrador', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def cliente_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'cliente_id' not in session:
            flash('Por favor inicia sesión como cliente', 'error')
            return redirect(url_for('login_cliente'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_id' not in session or session.get('usuario_rol') != 'administrador':
            flash('No tienes permisos de administrador', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def calcular_iva(subtotal, porcentaje_iva=16):
    """Calcular IVA basado en el subtotal"""
    return subtotal * (porcentaje_iva / 100)

def puede_cancelar_venta(fecha_venta):
    """Verificar si una venta puede ser cancelada (menos de 15 minutos)"""
    tiempo_transcurrido = datetime.now() - fecha_venta
    return tiempo_transcurrido.total_seconds() < 900  # 15 minutos = 900 segundos

# ----------------- INICIALIZAR DATOS -----------------
def inicializar_datos():
    # Verificar si existe al menos un usuario administrador
    if coleccion_usuarios.count_documents({}) == 0:
        usuario_admin = {
            'nombre': 'Administrador',
            'email': 'admin@biblioteca.com',
            'password': encriptar_password('admin123'),
            'rol': 'administrador',
            'activo': True,
            'fecha_registro': datetime.now()
        }
        coleccion_usuarios.insert_one(usuario_admin)
        print("Usuario administrador creado: admin@biblioteca.com / admin123")

# ----------------- RUTAS DE AUTENTICACIÓN -----------------

@app.route('/')
def index():
    if 'usuario_id' in session:
        return redirect(url_for('dashboard'))
    elif 'cliente_id' in session:
        return redirect(url_for('catalogo_cliente'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Verificar si es administrador
        usuario = coleccion_usuarios.find_one({
            'email': email, 
            'password': encriptar_password(password),
            'activo': True
        })
        
        if usuario:
            session['usuario_id'] = str(usuario['_id'])
            session['usuario_nombre'] = usuario['nombre']
            session['usuario_rol'] = usuario['rol']
            flash('¡Bienvenido ' + usuario['nombre'] + '!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciales incorrectas', 'error')
    
    return render_template('login.html')

@app.route('/login-cliente', methods=['GET', 'POST'])
def login_cliente():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Verificar si es cliente
        cliente = coleccion_clientes.find_one({
            'email': email, 
            'password': encriptar_password(password),
            'activo': True
        })
        
        if cliente:
            session['cliente_id'] = str(cliente['_id'])
            session['cliente_nombre'] = cliente['nombre']
            session['cliente_email'] = cliente['email']
            # Inicializar carrito vacío
            session['carrito'] = []
            flash('¡Bienvenido ' + cliente['nombre'] + '!', 'success')
            return redirect(url_for('catalogo_cliente'))
        else:
            flash('Credenciales incorrectas', 'error')
    
    return render_template('login_cliente.html')

@app.route('/registro-cliente', methods=['GET', 'POST'])
def registro_cliente():
    if request.method == 'POST':
        try:
            # Verificar si el email ya existe
            cliente_existente = coleccion_clientes.find_one({'email': request.form.get('email')})
            if cliente_existente:
                flash('El email ya está registrado', 'error')
                return render_template('registro_cliente.html')
            
            # Obtener la contraseña del formulario
            password = request.form.get('password')
            if not password:
                flash('La contraseña es requerida', 'error')
                return render_template('registro_cliente.html')
            
            cliente = {
                'nombre': request.form.get('nombre'),
                'email': request.form.get('email'),
                'password': encriptar_password(password),
                'telefono': request.form.get('telefono'),
                'direccion': {
                    'calle': request.form.get('calle'),
                    'ciudad': request.form.get('ciudad'),
                    'codigo_postal': request.form.get('codigo_postal')
                },
                'fecha_registro': datetime.now(),
                'activo': True
            }
            coleccion_clientes.insert_one(cliente)
            flash('Cliente registrado exitosamente. Ahora puedes iniciar sesión.', 'success')
            return redirect(url_for('login_cliente'))
        except Exception as e:
            flash(f'Error al registrar cliente: {e}', 'error')
    
    return render_template('registro_cliente.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada correctamente', 'success')
    return redirect(url_for('login'))

# ----------------- DASHBOARD ADMIN CON GRÁFICOS -----------------

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        total_libros = coleccion_libros.count_documents({})
        total_clientes = coleccion_clientes.count_documents({'activo': True})
        total_ventas = coleccion_ventas.count_documents({})
        
        inicio_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ventas_mes_cursor = coleccion_ventas.find({'fecha_venta': {'$gte': inicio_mes}})
        ventas_mes = list(ventas_mes_cursor)
        total_ventas_mes = sum(venta.get('total', 0) for venta in ventas_mes)
        
        libros_stock_bajo = list(coleccion_libros.find({'stock': {'$lt': 5}}))
        
        # Ventas recientes
        ventas_recientes_cursor = coleccion_ventas.find().sort('fecha_venta', -1).limit(5)
        ventas_recientes = list(ventas_recientes_cursor)
        
        for venta in ventas_recientes:
            if 'cliente_nombre' not in venta:
                cliente = coleccion_clientes.find_one({'_id': ObjectId(venta['cliente_id'])})
                venta['cliente_nombre'] = cliente['nombre'] if cliente else 'Cliente no encontrado'
        
        # Datos para gráficos
        # Top 5 libros más vendidos
        pipeline_libros = [
            {"$unwind": "$items"},
            {"$group": {
                "_id": "$items.libro_id",
                "titulo": {"$first": "$items.titulo"},
                "total_vendido": {"$sum": "$items.cantidad"},
                "total_ingresos": {"$sum": "$items.subtotal"}
            }},
            {"$sort": {"total_vendido": -1}},
            {"$limit": 5}
        ]
        libros_mas_vendidos = list(coleccion_ventas.aggregate(pipeline_libros))
        
        # Top 5 clientes más frecuentes
        pipeline_clientes = [
            {"$group": {
                "_id": "$cliente_id",
                "cliente_nombre": {"$first": "$cliente_nombre"},
                "total_compras": {"$sum": 1},
                "total_gastado": {"$sum": "$total"}
            }},
            {"$sort": {"total_compras": -1}},
            {"$limit": 5}
        ]
        clientes_frecuentes = list(coleccion_ventas.aggregate(pipeline_clientes))
        
        # Ventas por día últimos 7 días
        fecha_inicio = datetime.now() - timedelta(days=7)
        pipeline_ventas_diarias = [
            {"$match": {"fecha_venta": {"$gte": fecha_inicio}}},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$fecha_venta"}},
                "total_ventas": {"$sum": 1},
                "total_ingresos": {"$sum": "$total"}
            }},
            {"$sort": {"_id": 1}}
        ]
        ventas_diarias = list(coleccion_ventas.aggregate(pipeline_ventas_diarias))
        
        # Preparar datos para gráficos
        fechas = [v['_id'] for v in ventas_diarias]
        ventas_por_dia = [v['total_ventas'] for v in ventas_diarias]
        ingresos_por_dia = [v['total_ingresos'] for v in ventas_diarias]
        
        nombres_libros = [libro['titulo'] for libro in libros_mas_vendidos]
        ventas_libros = [libro['total_vendido'] for libro in libros_mas_vendidos]
        
        nombres_clientes = [cliente['cliente_nombre'] for cliente in clientes_frecuentes]
        compras_clientes = [cliente['total_compras'] for cliente in clientes_frecuentes]
        
        return render_template('dashboard.html',
                             total_libros=total_libros,
                             total_clientes=total_clientes,
                             total_ventas=total_ventas,
                             total_ventas_mes=total_ventas_mes,
                             libros_stock_bajo=libros_stock_bajo,
                             ventas_recientes=ventas_recientes,
                             libros_mas_vendidos=libros_mas_vendidos,
                             clientes_frecuentes=clientes_frecuentes,
                             fechas=json.dumps(fechas),
                             ventas_por_dia=json.dumps(ventas_por_dia),
                             ingresos_por_dia=json.dumps(ingresos_por_dia),
                             nombres_libros=json.dumps(nombres_libros),
                             ventas_libros=json.dumps(ventas_libros),
                             nombres_clientes=json.dumps(nombres_clientes),
                             compras_clientes=json.dumps(compras_clientes))
    except Exception as e:
        flash(f'Error al cargar dashboard: {e}', 'error')
        return render_template('dashboard.html')

# ----------------- CRUD USUARIOS (ADMIN) -----------------

@app.route('/usuarios')
@login_required
@admin_required
def listar_usuarios():
    try:
        usuarios = list(coleccion_usuarios.find({'activo': True}))
        return render_template('usuarios.html', usuarios=usuarios)
    except Exception as e:
        flash(f'Error al cargar usuarios: {e}', 'error')
        return render_template('usuarios.html', usuarios=[])

@app.route('/usuarios/agregar', methods=['GET', 'POST'])
@login_required
@admin_required
def agregar_usuario():
    if request.method == 'POST':
        try:
            # Verificar si el email ya existe
            usuario_existente = coleccion_usuarios.find_one({'email': request.form.get('email')})
            if usuario_existente:
                flash('El email ya está registrado', 'error')
                return render_template('agregar_usuario.html')
            
            usuario = {
                'nombre': request.form.get('nombre'),
                'email': request.form.get('email'),
                'password': encriptar_password(request.form.get('password')),
                'rol': request.form.get('rol', 'empleado'),
                'activo': True,
                'fecha_registro': datetime.now()
            }
            coleccion_usuarios.insert_one(usuario)
            flash('Usuario agregado exitosamente', 'success')
            return redirect(url_for('listar_usuarios'))
        except Exception as e:
            flash(f'Error al crear el usuario: {e}', 'error')
    
    return render_template('agregar_usuario.html')

@app.route('/usuarios/editar/<id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_usuario(id):
    try:
        usuario = coleccion_usuarios.find_one({'_id': ObjectId(id)})
        if not usuario:
            flash('Usuario no encontrado', 'error')
            return redirect(url_for('listar_usuarios'))
        
        if request.method == 'POST':
            datos_actualizados = {
                'nombre': request.form.get('nombre'),
                'email': request.form.get('email'),
                'rol': request.form.get('rol', 'empleado')
            }
            
            # Si se proporciona una nueva contraseña, actualizarla
            nueva_password = request.form.get('password')
            if nueva_password:
                datos_actualizados['password'] = encriptar_password(nueva_password)
            
            resultado = coleccion_usuarios.update_one(
                {'_id': ObjectId(id)},
                {'$set': datos_actualizados}
            )
            
            if resultado.modified_count > 0:
                flash('Usuario actualizado exitosamente', 'success')
            else:
                flash('No se realizaron cambios en el usuario', 'info')
                
            return redirect(url_for('listar_usuarios'))
        
        return render_template('editar_usuario.html', usuario=usuario)
    
    except Exception as e:
        flash(f'Error al editar usuario: {str(e)}', 'error')
        return redirect(url_for('listar_usuarios'))

@app.route('/usuarios/eliminar/<id>', methods=['POST'])
@login_required
@admin_required
def eliminar_usuario(id):
    try:
        # No permitir eliminar el propio usuario
        if str(id) == session['usuario_id']:
            flash('No puedes eliminar tu propio usuario', 'error')
            return redirect(url_for('listar_usuarios'))
        
        coleccion_usuarios.update_one(
            {'_id': ObjectId(id)},
            {'$set': {'activo': False}}
        )
        flash('Usuario eliminado exitosamente', 'success')
    except Exception as e:
        flash(f'Error al eliminar usuario: {e}', 'error')
    
    return redirect(url_for('listar_usuarios'))

# ----------------- CRUD LIBROS CON IMÁGENES -----------------

@app.route('/libros')
@login_required
def listar_libros():
    try:
        query = request.args.get('q', '')
        if query:
            libros = list(coleccion_libros.find({
                '$or': [
                    {'nombre': {'$regex': query, '$options': 'i'}},
                    {'autor': {'$regex': query, '$options': 'i'}},
                    {'genero': {'$regex': query, '$options': 'i'}},
                    {'isbn': {'$regex': query, '$options': 'i'}}
                ]
            }))
        else:
            libros = list(coleccion_libros.find())
        return render_template('libros.html', libros=libros, query=query)
    except Exception as e:
        flash(f'Error al cargar libros: {e}', 'error')
        return render_template('libros.html', libros=[], query='')

@app.route('/libros/agregar', methods=['GET', 'POST'])
@login_required
def agregar_libro():
    if request.method == 'POST':
        try:
            # Manejar carga de imagen
            imagen_url = ''
            if 'imagen' in request.files:
                imagen = request.files['imagen']
                if imagen.filename != '':
                    # Guardar imagen
                    filename = f"libro_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{imagen.filename}"
                    imagen_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    imagen.save(imagen_path)
                    imagen_url = f"/static/uploads/{filename}"
            
            libro = {
                'nombre': request.form.get('nombre'),         
                'autor': request.form.get('autor'),
                'genero': request.form.get('genero'),         
                'stock': int(request.form.get('stock', 0)), 
                'isbn': request.form.get('isbn'),
                'anio_publicacion': int(request.form.get('anio_publicacion', 0)),
                'precio': float(request.form.get('precio', 0)),
                'descripcion': request.form.get('descripcion', ''),
                'imagen_url': imagen_url,
                'fecha_agregado': datetime.now()
            }
            coleccion_libros.insert_one(libro)
            flash('Libro agregado exitosamente', 'success')
            return redirect(url_for('listar_libros'))
        except Exception as e:
            flash(f'Error al crear el libro: {e}', 'error')
    
    return render_template('agregar_libro.html')

@app.route('/libros/editar/<id>', methods=['GET', 'POST'])
@login_required
def editar_libro(id):
    try:
        libro = coleccion_libros.find_one({'_id': ObjectId(id)})
        
        if request.method == 'POST':
            datos_actualizados = {
                'nombre': request.form.get('nombre'),         
                'autor': request.form.get('autor'),
                'genero': request.form.get('genero'),
                'stock': int(request.form.get('stock', 0)),
                'isbn': request.form.get('isbn'),
                'anio_publicacion': int(request.form.get('anio_publicacion', 0)),
                'precio': float(request.form.get('precio', 0)),
                'descripcion': request.form.get('descripcion', '')
            }
            
            # Manejar nueva imagen si se sube
            if 'imagen' in request.files:
                imagen = request.files['imagen']
                if imagen.filename != '':
                    filename = f"libro_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{imagen.filename}"
                    imagen_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    imagen.save(imagen_path)
                    datos_actualizados['imagen_url'] = f"/static/uploads/{filename}"
            
            coleccion_libros.update_one(
                {'_id': ObjectId(id)},
                {'$set': datos_actualizados}
            )
            flash('Libro actualizado exitosamente', 'success')
            return redirect(url_for('listar_libros'))
        
        return render_template('editar_libro.html', libro=libro)
    
    except Exception as e:
        flash(f'Error: {e}', 'error')
        return redirect(url_for('listar_libros'))

@app.route('/libros/eliminar/<id>', methods=['POST'])
@login_required
def eliminar_libro(id):
    try:
        coleccion_libros.delete_one({'_id': ObjectId(id)})
        flash('Libro eliminado exitosamente', 'success')
    except Exception as e:
        flash(f'Error al eliminar libro: {e}', 'error')
    
    return redirect(url_for('listar_libros'))

# ----------------- CRUD CLIENTES (ADMIN) -----------------

@app.route('/clientes')
@login_required
def listar_clientes():
    try:
        clientes = list(coleccion_clientes.find({'activo': True}))
        return render_template('clientes.html', clientes=clientes)
    except Exception as e:
        flash(f'Error al cargar clientes: {e}', 'error')
        return render_template('clientes.html', clientes=[])

@app.route('/clientes/agregar', methods=['GET', 'POST'])
@login_required
def agregar_cliente():
    if request.method == 'POST':
        try:
            # Obtener la contraseña del formulario
            password = request.form.get('password')
            if not password:
                password = 'cliente123'  # Contraseña por defecto
            
            cliente = {
                'nombre': request.form.get('nombre'),
                'email': request.form.get('email'),
                'password': encriptar_password(password),
                'telefono': request.form.get('telefono'),
                'direccion': {
                    'calle': request.form.get('calle'),
                    'ciudad': request.form.get('ciudad'),
                    'codigo_postal': request.form.get('codigo_postal')
                },
                'fecha_registro': datetime.now(),
                'activo': True
            }
            coleccion_clientes.insert_one(cliente)
            flash('Cliente agregado exitosamente', 'success')
            return redirect(url_for('listar_clientes'))
        except Exception as e:
            flash(f'Error al agregar cliente: {e}', 'error')
    
    return render_template('agregar_cliente.html')

@app.route('/clientes/editar/<id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    try:
        cliente = coleccion_clientes.find_one({'_id': ObjectId(id)})
        if not cliente:
            flash('Cliente no encontrado', 'error')
            return redirect(url_for('listar_clientes'))
        
        if request.method == 'POST':
            datos_actualizados = {
                'nombre': request.form.get('nombre'),
                'email': request.form.get('email'),
                'telefono': request.form.get('telefono'),
                'direccion': {
                    'calle': request.form.get('calle'),
                    'ciudad': request.form.get('ciudad'),
                    'codigo_postal': request.form.get('codigo_postal')
                }
            }
            
            # Si se proporciona una nueva contraseña, actualizarla
            nueva_password = request.form.get('password')
            if nueva_password:
                datos_actualizados['password'] = encriptar_password(nueva_password)
            
            resultado = coleccion_clientes.update_one(
                {'_id': ObjectId(id)},
                {'$set': datos_actualizados}
            )
            
            if resultado.modified_count > 0:
                flash('Cliente actualizado exitosamente', 'success')
            else:
                flash('No se realizaron cambios en el cliente', 'info')
                
            return redirect(url_for('listar_clientes'))
        
        return render_template('editar_cliente.html', cliente=cliente)
    
    except Exception as e:
        flash(f'Error al editar cliente: {str(e)}', 'error')
        return redirect(url_for('listar_clientes'))

@app.route('/clientes/eliminar/<id>', methods=['POST'])
@login_required
def eliminar_cliente(id):
    try:
        coleccion_clientes.update_one(
            {'_id': ObjectId(id)},
            {'$set': {'activo': False}}
        )
        flash('Cliente eliminado exitosamente', 'success')
    except Exception as e:
        flash(f'Error al eliminar cliente: {e}', 'error')
    
    return redirect(url_for('listar_clientes'))

# ----------------- VENTAS CON CANCELACIONES -----------------

@app.route('/ventas')
@login_required
def listar_ventas():
    try:
        pagina = int(request.args.get('pagina', 1))
        ventas_por_pagina = 10
        
        # Calcular paginación
        total_ventas = coleccion_ventas.count_documents({})
        total_paginas = (total_ventas + ventas_por_pagina - 1) // ventas_por_pagina
        
        skip = (pagina - 1) * ventas_por_pagina
        ventas_cursor = coleccion_ventas.find().sort('fecha_venta', -1).skip(skip).limit(ventas_por_pagina)
        ventas = list(ventas_cursor)
        
        for venta in ventas:
            # Asegurarse de que tenemos información del cliente
            if 'cliente_nombre' not in venta:
                cliente = coleccion_clientes.find_one({'_id': ObjectId(venta['cliente_id'])})
                if cliente:
                    venta['cliente_nombre'] = cliente['nombre']
                    venta['cliente_email'] = cliente['email']
                    venta['cliente_telefono'] = cliente.get('telefono', '')
                else:
                    venta['cliente_nombre'] = 'Cliente no encontrado'
                    venta['cliente_email'] = ''
                    venta['cliente_telefono'] = ''
            
            # Asegurarse de que tenemos información del usuario
            if 'usuario_nombre' not in venta and 'usuario_id' in venta:
                usuario = coleccion_usuarios.find_one({'_id': ObjectId(venta['usuario_id'])})
                venta['usuario_nombre'] = usuario['nombre'] if usuario else 'Usuario no encontrado'
            
            # Verificar si puede ser cancelada
            venta['puede_cancelar'] = puede_cancelar_venta(venta['fecha_venta'])
            
            # Verificar si ya está cancelada
            cancelacion = coleccion_cancelaciones.find_one({'venta_id': str(venta['_id'])})
            venta['cancelada'] = cancelacion is not None
            if cancelacion:
                venta['razon_cancelacion'] = cancelacion.get('razon', '')
                venta['fecha_cancelacion'] = cancelacion.get('fecha_cancelacion', '')
        
        # Fechas para los filtros de reportes
        hoy = datetime.now().strftime('%Y-%m-%d')
        mes_actual = datetime.now().strftime('%Y-%m')
        anio_actual = datetime.now().year
        
        return render_template('ventas.html', 
                             ventas=ventas,
                             pagina=pagina,
                             total_paginas=total_paginas,
                             hoy=hoy,
                             mes_actual=mes_actual,
                             anio_actual=anio_actual)
    except Exception as e:
        flash(f'Error al cargar ventas: {str(e)}', 'error')
        return render_template('ventas.html', ventas=[])

@app.route('/ventas/cancelar/<id>', methods=['POST'])
@login_required
def cancelar_venta(id):
    try:
        venta = coleccion_ventas.find_one({'_id': ObjectId(id)})
        if not venta:
            flash('Venta no encontrada', 'error')
            return redirect(url_for('listar_ventas'))
        
        # Verificar si ya está cancelada
        cancelacion_existente = coleccion_cancelaciones.find_one({'venta_id': id})
        if cancelacion_existente:
            flash('Esta venta ya ha sido cancelada', 'error')
            return redirect(url_for('listar_ventas'))
        
        # Verificar tiempo (15 minutos)
        if not puede_cancelar_venta(venta['fecha_venta']):
            flash('No se puede cancelar la venta después de 15 minutos', 'error')
            return redirect(url_for('listar_ventas'))
        
        razon = request.form.get('razon', 'Cancelación solicitada por el cliente')
        
        # Crear registro de cancelación
        cancelacion = {
            'venta_id': id,
            'cliente_id': venta['cliente_id'],
            'cliente_nombre': venta.get('cliente_nombre', ''),
            'total_venta': venta['total'],
            'razon': razon,
            'cancelado_por': session['usuario_id'],
            'cancelado_por_nombre': session['usuario_nombre'],
            'fecha_cancelacion': datetime.now(),
            'fecha_venta_original': venta['fecha_venta']
        }
        
        # Devolver stock de libros
        for item in venta.get('items', []):
            libro_id = item['libro_id']
            cantidad = item['cantidad']
            
            libro = coleccion_libros.find_one({'_id': ObjectId(libro_id)})
            if libro:
                nuevo_stock = libro.get('stock', 0) + cantidad
                coleccion_libros.update_one(
                    {'_id': ObjectId(libro_id)},
                    {'$set': {'stock': nuevo_stock}}
                )
        
        # Guardar cancelación
        coleccion_cancelaciones.insert_one(cancelacion)
        
        # Marcar venta como cancelada
        coleccion_ventas.update_one(
            {'_id': ObjectId(id)},
            {'$set': {'estado': 'cancelada'}}
        )
        
        flash('Venta cancelada exitosamente. Stock devuelto a inventario.', 'success')
        return redirect(url_for('listar_ventas'))
        
    except Exception as e:
        flash(f'Error al cancelar venta: {str(e)}', 'error')
        return redirect(url_for('listar_ventas'))

@app.route('/ventas/nueva', methods=['GET', 'POST'])
@login_required
def nueva_venta():
    if request.method == 'POST':
        try:
            cliente_id = request.form.get('cliente_id')
            if not cliente_id:
                flash('Selecciona un cliente', 'error')
                return redirect(url_for('nueva_venta'))
            
            items = []
            libro_ids = request.form.getlist('libro_id[]')
            cantidades = request.form.getlist('cantidad[]')
            
            subtotal_venta = 0
            
            for i, libro_id in enumerate(libro_ids):
                if libro_id and cantidades[i] and int(cantidades[i]) > 0:
                    cantidad = int(cantidades[i])
                    libro = coleccion_libros.find_one({'_id': ObjectId(libro_id)})
                    
                    if libro and libro.get('stock', 0) >= cantidad:
                        precio = libro.get('precio', 0)
                        subtotal = precio * cantidad
                        subtotal_venta += subtotal
                        
                        # Guardar información completa del libro
                        items.append({
                            'libro_id': str(libro['_id']),
                            'titulo': libro['nombre'],
                            'autor': libro.get('autor', ''),
                            'genero': libro.get('genero', ''),
                            'isbn': libro.get('isbn', ''),
                            'cantidad': cantidad,
                            'precio_unitario': precio,
                            'subtotal': subtotal
                        })
                        
                        # Actualizar stock
                        nuevo_stock = libro['stock'] - cantidad
                        coleccion_libros.update_one(
                            {'_id': ObjectId(libro_id)},
                            {'$set': {'stock': nuevo_stock}}
                        )
                    else:
                        libro_nombre = libro['nombre'] if libro else 'Libro desconocido'
                        flash(f'Stock insuficiente para {libro_nombre}', 'error')
                        return redirect(url_for('nueva_venta'))
            
            if not items:
                flash('Agrega al menos un libro a la venta', 'error')
                return redirect(url_for('nueva_venta'))
            
            # Calcular IVA y total
            iva_venta = calcular_iva(subtotal_venta)
            total_con_iva = subtotal_venta + iva_venta
            
            # Obtener información completa del cliente
            cliente = coleccion_clientes.find_one({'_id': ObjectId(cliente_id)})
            
            # Crear venta con información completa e IVA
            venta = {
                'cliente_id': cliente_id,
                'cliente_nombre': cliente['nombre'] if cliente else 'Cliente no encontrado',
                'cliente_email': cliente['email'] if cliente else '',
                'cliente_telefono': cliente.get('telefono', ''),
                'usuario_id': session['usuario_id'],
                'usuario_nombre': session['usuario_nombre'],
                'items': items,
                'subtotal': subtotal_venta,
                'iva': iva_venta,
                'total': total_con_iva,
                'fecha_venta': datetime.now(),
                'estado': 'completada',
                'tipo': 'presencial'
            }
            
            resultado = coleccion_ventas.insert_one(venta)
            flash(f'Venta registrada exitosamente! Total con IVA: ${total_con_iva:.2f}', 'success')
            return redirect(url_for('ver_venta', id=resultado.inserted_id))
            
        except Exception as e:
            flash(f'Error al procesar venta: {str(e)}', 'error')
    
    clientes = list(coleccion_clientes.find({'activo': True}))
    libros = list(coleccion_libros.find({'stock': {'$gt': 0}}))
    return render_template('nueva_venta.html', clientes=clientes, libros=libros)

@app.route('/ventas/<id>')
@login_required
def ver_venta(id):
    try:
        venta = coleccion_ventas.find_one({'_id': ObjectId(id)})
        if not venta:
            flash('Venta no encontrada', 'error')
            return redirect(url_for('listar_ventas'))
        
        # Verificar cancelación
        cancelacion = coleccion_cancelaciones.find_one({'venta_id': id})
        venta['cancelada'] = cancelacion is not None
        if cancelacion:
            venta['razon_cancelacion'] = cancelacion.get('razon', '')
            venta['fecha_cancelacion'] = cancelacion.get('fecha_cancelacion', '')
        
        venta['puede_cancelar'] = puede_cancelar_venta(venta['fecha_venta'])
        
        return render_template('ver_venta.html', venta=venta)
    except Exception as e:
        flash(f'Error al cargar venta: {e}', 'error')
        return redirect(url_for('listar_ventas'))

# ----------------- SEGUIMIENTO DE PEDIDOS ONLINE -----------------

@app.route('/seguimiento-pedidos')
@login_required
def seguimiento_pedidos():
    try:
        # Obtener pedidos online pendientes
        pedidos = list(coleccion_ventas.find({
            'tipo': 'online',
            'estado': {'$in': ['pendiente', 'en_proceso', 'enviado']}
        }).sort('fecha_venta', -1))
        
        # Obtener estados de seguimiento si existen
        for pedido in pedidos:
            seguimiento = coleccion_pedidos.find_one({'venta_id': str(pedido['_id'])})
            if seguimiento:
                pedido['estado_seguimiento'] = seguimiento.get('estado', 'pendiente')
                pedido['ultima_actualizacion'] = seguimiento.get('ultima_actualizacion', '')
                pedido['comentarios'] = seguimiento.get('comentarios', [])
            else:
                # Crear registro de seguimiento si no existe
                nuevo_seguimiento = {
                    'venta_id': str(pedido['_id']),
                    'cliente_id': pedido['cliente_id'],
                    'cliente_nombre': pedido.get('cliente_nombre', ''),
                    'estado': 'pendiente',
                    'fecha_pedido': pedido['fecha_venta'],
                    'ultima_actualizacion': pedido['fecha_venta'],
                    'comentarios': [{
                        'fecha': pedido['fecha_venta'],
                        'mensaje': 'Pedido recibido',
                        'usuario': 'Sistema'
                    }]
                }
                coleccion_pedidos.insert_one(nuevo_seguimiento)
                pedido['estado_seguimiento'] = 'pendiente'
                pedido['ultima_actualizacion'] = pedido['fecha_venta']
                pedido['comentarios'] = nuevo_seguimiento['comentarios']
        
        return render_template('seguimiento_pedidos.html', pedidos=pedidos)
    except Exception as e:
        flash(f'Error al cargar pedidos: {str(e)}', 'error')
        return render_template('seguimiento_pedidos.html', pedidos=[])

@app.route('/actualizar-estado-pedido/<id>', methods=['POST'])
@login_required
def actualizar_estado_pedido(id):
    try:
        nuevo_estado = request.form.get('estado')
        comentario = request.form.get('comentario', '')
        
        if not nuevo_estado:
            flash('Selecciona un estado', 'error')
            return redirect(url_for('seguimiento_pedidos'))
        
        pedido = coleccion_pedidos.find_one({'venta_id': id})
        if not pedido:
            # Buscar la venta
            venta = coleccion_ventas.find_one({'_id': ObjectId(id)})
            if not venta:
                flash('Pedido no encontrado', 'error')
                return redirect(url_for('seguimiento_pedidos'))
            
            pedido = {
                'venta_id': id,
                'cliente_id': venta['cliente_id'],
                'cliente_nombre': venta.get('cliente_nombre', ''),
                'estado': nuevo_estado,
                'fecha_pedido': venta['fecha_venta'],
                'ultima_actualizacion': datetime.now(),
                'comentarios': [{
                    'fecha': venta['fecha_venta'],
                    'mensaje': 'Pedido recibido',
                    'usuario': 'Sistema'
                }]
            }
        
        # Actualizar estado
        coleccion_pedidos.update_one(
            {'venta_id': id},
            {'$set': {
                'estado': nuevo_estado,
                'ultima_actualizacion': datetime.now()
            }}
        )
        
        # Agregar comentario si hay
        if comentario:
            nuevo_comentario = {
                'fecha': datetime.now(),
                'mensaje': comentario,
                'usuario': session['usuario_nombre']
            }
            coleccion_pedidos.update_one(
                {'venta_id': id},
                {'$push': {'comentarios': nuevo_comentario}}
            )
        
        # Actualizar estado en ventas también
        coleccion_ventas.update_one(
            {'_id': ObjectId(id)},
            {'$set': {'estado': nuevo_estado}}
        )
        
        flash(f'Estado del pedido actualizado a: {nuevo_estado}', 'success')
        return redirect(url_for('seguimiento_pedidos'))
        
    except Exception as e:
        flash(f'Error al actualizar pedido: {str(e)}', 'error')
        return redirect(url_for('seguimiento_pedidos'))

@app.route('/mi-seguimiento')
@cliente_required
def mi_seguimiento():
    try:
        # Obtener pedidos del cliente
        pedidos = list(coleccion_ventas.find({
            'cliente_id': session['cliente_id'],
            'tipo': 'online'
        }).sort('fecha_venta', -1))
        
        # Obtener información de seguimiento
        for pedido in pedidos:
            seguimiento = coleccion_pedidos.find_one({'venta_id': str(pedido['_id'])})
            if seguimiento:
                pedido['estado_seguimiento'] = seguimiento.get('estado', 'pendiente')
                pedido['ultima_actualizacion'] = seguimiento.get('ultima_actualizacion', '')
                pedido['comentarios'] = seguimiento.get('comentarios', [])
            else:
                pedido['estado_seguimiento'] = 'pendiente'
                pedido['ultima_actualizacion'] = pedido['fecha_venta']
                pedido['comentarios'] = []
        
        return render_template('mi_seguimiento.html', pedidos=pedidos)
    except Exception as e:
        flash(f'Error al cargar seguimiento: {str(e)}', 'error')
        return render_template('mi_seguimiento.html', pedidos=[])

# NUEVA RUTA: Buscar pedido específico
@app.route('/seguimiento_pedido', methods=['GET', 'POST'])
@cliente_required
def seguimiento_pedido_cliente():
    """Permite al cliente buscar un pedido específico por su ID"""
    pedido_id = None
    pedido = None
    
    if request.method == 'POST':
        pedido_id = request.form.get('pedido_id')
    else:
        pedido_id = request.args.get('id')
    
    if pedido_id:
        try:
            # Buscar el pedido por ID
            pedido = coleccion_ventas.find_one({
                '_id': ObjectId(pedido_id),
                'cliente_id': session['cliente_id']
            })
            
            if not pedido:
                flash('Pedido no encontrado o no tienes permisos para verlo', 'error')
                return redirect(url_for('mi_seguimiento'))
            
            # Obtener información de seguimiento
            seguimiento = coleccion_pedidos.find_one({'venta_id': str(pedido['_id'])})
            if seguimiento:
                pedido['estado_seguimiento'] = seguimiento.get('estado', 'pendiente')
                pedido['ultima_actualizacion'] = seguimiento.get('ultima_actualizacion', '')
                pedido['comentarios'] = seguimiento.get('comentarios', [])
            else:
                pedido['estado_seguimiento'] = 'pendiente'
                pedido['ultima_actualizacion'] = pedido['fecha_venta']
                pedido['comentarios'] = []
            
            # Obtener información completa del cliente
            cliente = coleccion_clientes.find_one({'_id': ObjectId(session['cliente_id'])})
            if cliente:
                pedido['cliente_nombre'] = cliente.get('nombre', 'Cliente')
                pedido['cliente_email'] = cliente.get('email', '')
                pedido['cliente_direccion'] = cliente.get('direccion', '')
                pedido['cliente_telefono'] = cliente.get('telefono', '')
            
            return render_template('seguimiento_detalle_cliente.html', 
                                pedido=pedido,
                                cliente=cliente)
            
        except Exception as e:
            print(f"Error al buscar pedido: {e}")
            flash('Error al buscar el pedido. Verifica el ID e intenta nuevamente.', 'error')
            return render_template('buscar_seguimiento.html')
    
    # Si no hay ID, mostrar formulario para buscarlo
    return render_template('buscar_seguimiento.html')

# ----------------- API PARA SEGUIMIENTO (para cliente) -----------------

@app.route('/api/seguimiento/<venta_id>')
@cliente_required
def api_seguimiento(venta_id):
    try:
        # Verificar que el pedido pertenece al cliente
        venta = coleccion_ventas.find_one({
            '_id': ObjectId(venta_id),
            'cliente_id': session['cliente_id']
        })
        
        if not venta:
            return jsonify({'error': 'Pedido no encontrado'}), 404
        
        seguimiento = coleccion_pedidos.find_one({'venta_id': venta_id})
        if not seguimiento:
            return jsonify({
                'venta_id': venta_id,
                'estado': 'pendiente',
                'ultima_actualizacion': venta['fecha_venta'].strftime('%Y-%m-%d %H:%M'),
                'comentarios': []
            })
        
        # Convertir a JSON serializable
        seguimiento_data = {
            'venta_id': seguimiento['venta_id'],
            'estado': seguimiento['estado'],
            'ultima_actualizacion': seguimiento['ultima_actualizacion'].strftime('%Y-%m-%d %H:%M'),
            'comentarios': seguimiento.get('comentarios', [])
        }
        
        return jsonify(seguimiento_data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ----------------- COMPROBANTE DE VENTA -----------------

@app.route('/ventas/<id>/comprobante')
@login_required
def comprobante_venta(id):
    try:
        venta = coleccion_ventas.find_one({'_id': ObjectId(id)})
        if not venta:
            return "Venta no encontrada", 404
        
        # Crear PDF
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # Configuración inicial
        pdf.setTitle(f"Comprobante de Venta - {venta['_id']}")
        
        # Encabezado
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(100, height - 50, "BIBLIOTECA DIGITAL")
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(100, height - 70, "COMPROBANTE DE VENTA")
        pdf.line(100, height - 75, 500, height - 75)
        
        # Información de la venta
        y_position = height - 100
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "INFORMACIÓN DE LA VENTA:")
        pdf.setFont("Helvetica", 10)
        y_position -= 15
        pdf.drawString(100, y_position, f"Folio: {str(venta['_id'])}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Fecha: {venta['fecha_venta'].strftime('%d/%m/%Y')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Hora: {venta['fecha_venta'].strftime('%H:%M:%S')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Estado: {venta.get('estado', 'Completada')}")
        
        # Información del cliente
        y_position -= 25
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "INFORMACIÓN DEL CLIENTE:")
        pdf.setFont("Helvetica", 10)
        y_position -= 15
        pdf.drawString(100, y_position, f"Nombre: {venta.get('cliente_nombre', 'N/A')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Email: {venta.get('cliente_email', 'N/A')}")
        if venta.get('cliente_telefono'):
            y_position -= 15
            pdf.drawString(100, y_position, f"Teléfono: {venta['cliente_telefono']}")
        
        # Información del vendedor
        y_position -= 25
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "INFORMACIÓN DEL VENDEDOR:")
        pdf.setFont("Helvetica", 10)
        y_position -= 15
        pdf.drawString(100, y_position, f"Atendió: {venta.get('usuario_nombre', 'N/A')}")
        
        # Tabla de productos
        y_position -= 30
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "DETALLE DE PRODUCTOS:")
        
        # Encabezados de la tabla
        y_position -= 20
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(100, y_position, "Producto")
        pdf.drawString(300, y_position, "Cant.")
        pdf.drawString(350, y_position, "Precio Unit.")
        pdf.drawString(450, y_position, "Subtotal")
        
        y_position -= 10
        pdf.line(100, y_position, 500, y_position)
        y_position -= 10
        
        # Items de la venta
        pdf.setFont("Helvetica", 9)
        for item in venta.get('items', []):
            if y_position < 150:  # Nueva página si es necesario
                pdf.showPage()
                y_position = height - 50
                pdf.setFont("Helvetica", 9)
            
            # Título del libro
            titulo = item['titulo']
            if len(titulo) > 40:
                titulo = titulo[:37] + "..."
            
            pdf.drawString(100, y_position, titulo)
            pdf.drawString(300, y_position, str(item['cantidad']))
            pdf.drawString(350, y_position, f"${item['precio_unitario']:.2f}")
            pdf.drawString(450, y_position, f"${item['subtotal']:.2f}")
            
            y_position -= 20
        
        # Línea separadora
        y_position -= 10
        pdf.line(100, y_position, 500, y_position)
        
        # Totales
        subtotal = venta.get('subtotal', 0)
        iva = venta.get('iva', 0)
        total = venta.get('total', 0)
        
        y_position -= 20
        pdf.setFont("Helvetica", 10)
        pdf.drawString(350, y_position, f"Subtotal: ${subtotal:.2f}")
        y_position -= 15
        pdf.drawString(350, y_position, f"IVA (16%): ${iva:.2f}")
        y_position -= 15
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(350, y_position, f"TOTAL: ${total:.2f}")
        
        # Pie de página con agradecimiento
        y_position -= 40
        pdf.setFont("Helvetica-Oblique", 10)
        pdf.drawString(100, y_position, "¡Gracias por su compra en Biblioteca Digital!")
        y_position -= 15
        pdf.drawString(100, y_position, "Esperamos volver a servirle pronto.")
        
        pdf.save()
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"comprobante_venta_{id}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        return f"Error al generar comprobante: {e}", 500

# ----------------- CLIENTE - CATÁLOGO CON IMÁGENES -----------------

@app.route('/catalogo')
@cliente_required
def catalogo_cliente():
    try:
        query = request.args.get('q', '')
        if query:
            libros = list(coleccion_libros.find({
                '$or': [
                    {'nombre': {'$regex': query, '$options': 'i'}},
                    {'autor': {'$regex': query, '$options': 'i'}},
                    {'genero': {'$regex': query, '$options': 'i'}}
                ],
                'stock': {'$gt': 0}
            }))
        else:
            libros = list(coleccion_libros.find({'stock': {'$gt': 0}}))
        
        # Inicializar carrito si no existe
        if 'carrito' not in session:
            session['carrito'] = []
        return render_template('catalogo_cliente.html', libros=libros, query=query)
    except Exception as e:
        flash(f'Error al cargar catálogo: {e}', 'error')
        return render_template('catalogo_cliente.html', libros=[], query='')

@app.route('/carrito/agregar', methods=['POST'])
@cliente_required
def agregar_carrito():
    try:
        libro_id = request.form.get('libro_id')
        cantidad = int(request.form.get('cantidad', 1))
        
        libro = coleccion_libros.find_one({'_id': ObjectId(libro_id)})
        if not libro:
            return jsonify({'éxito': False, 'error': 'Libro no encontrado'})
        
        if libro.get('stock', 0) < cantidad:
            return jsonify({'éxito': False, 'error': 'Stock insuficiente'})
        
        # Inicializar carrito si no existe - ¡CORREGIDO!
        carrito = session.get('carrito', [])
        
        # Verificar si el libro ya está en el carrito
        libro_en_carrito = None
        for item in carrito:
            if item['libro_id'] == libro_id:
                libro_en_carrito = item
                break
        
        if libro_en_carrito:
            # Actualizar cantidad si ya está en el carrito
            nueva_cantidad = libro_en_carrito['cantidad'] + cantidad
            if nueva_cantidad > libro['stock']:
                return jsonify({'éxito': False, 'error': 'Stock insuficiente para la cantidad solicitada'})
            libro_en_carrito['cantidad'] = nueva_cantidad
            libro_en_carrito['subtotal'] = libro['precio'] * nueva_cantidad
        else:
            # Agregar nuevo item al carrito
            carrito.append({
                'libro_id': libro_id,
                'titulo': libro['nombre'],
                'autor': libro.get('autor', ''),
                'precio': libro['precio'],
                'cantidad': cantidad,
                'subtotal': libro['precio'] * cantidad,
                'imagen_url': libro.get('imagen_url', '')
            })
        
        session['carrito'] = carrito
        session.modified = True
        
        return jsonify({
            'éxito': True,
            'carrito_count': len(carrito)
        })
        
    except Exception as e:
        return jsonify({'éxito': False, 'error': str(e)})

@app.route('/carrito')
@cliente_required
def ver_carrito():
    try:
        carrito = session.get('carrito', [])
        subtotal = sum(item['subtotal'] for item in carrito)
        iva = calcular_iva(subtotal)
        total = subtotal + iva
        return render_template('carrito.html', carrito=carrito, subtotal=subtotal, iva=iva, total=total)
    except Exception as e:
        flash(f'Error al cargar carrito: {e}', 'error')
        return render_template('carrito.html', carrito=[], subtotal=0, iva=0, total=0)

@app.route('/carrito/actualizar', methods=['POST'])
@cliente_required
def actualizar_carrito():
    try:
        libro_id = request.form.get('libro_id')
        nueva_cantidad = int(request.form.get('cantidad', 1))
        
        if nueva_cantidad <= 0:
            return jsonify({'success': False, 'message': 'La cantidad debe ser mayor a 0'})
        
        libro = coleccion_libros.find_one({'_id': ObjectId(libro_id)})
        if not libro:
            return jsonify({'success': False, 'message': 'Libro no encontrado'})
        
        if libro.get('stock', 0) < nueva_cantidad:
            return jsonify({'success': False, 'message': 'Stock insuficiente'})
        
        carrito = session.get('carrito', [])
        for item in carrito:
            if item['libro_id'] == libro_id:
                item['cantidad'] = nueva_cantidad
                item['subtotal'] = libro['precio'] * nueva_cantidad
                break
        
        session['carrito'] = carrito
        session.modified = True
        
        subtotal = sum(item['subtotal'] for item in carrito)
        iva = calcular_iva(subtotal)
        total = subtotal + iva
        
        return jsonify({
            'success': True, 
            'message': 'Carrito actualizado',
            'subtotal': subtotal,
            'iva': iva,
            'total': total
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/carrito/eliminar/<libro_id>', methods=['POST'])
@cliente_required
def eliminar_del_carrito(libro_id):
    try:
        carrito = session.get('carrito', [])
        carrito = [item for item in carrito if item['libro_id'] != libro_id]
        session['carrito'] = carrito
        session.modified = True
        
        flash('Libro eliminado del carrito', 'success')
        return redirect(url_for('ver_carrito'))
        
    except Exception as e:
        flash(f'Error al eliminar del carrito: {e}', 'error')
        return redirect(url_for('ver_carrito'))

@app.route('/carrito/vaciar', methods=['POST'])
@cliente_required
def vaciar_carrito():
    try:
        session['carrito'] = []
        session.modified = True
        flash('Carrito vaciado', 'success')
        return redirect(url_for('ver_carrito'))
    except Exception as e:
        flash(f'Error al vaciar carrito: {e}', 'error')
        return redirect(url_for('ver_carrito'))

@app.route('/carrito/comprar', methods=['POST'])
@cliente_required
def comprar_carrito():
    try:
        # ¡ESTO ES LO MÁS IMPORTANTE! DEBE TENER PARÉNTESIS
        carrito = session.get('carrito', [])  # ← ASÍ DEBE SER
        
        if not carrito:
            flash('El carrito está vacío', 'error')
            return redirect(url_for('ver_carrito'))
        
        items = []
        subtotal_venta = 0
        
        # Verificar stock y preparar items
        for item_carrito in carrito:
            libro = coleccion_libros.find_one({'_id': ObjectId(item_carrito['libro_id'])})
            if not libro:
                flash(f'Libro {item_carrito["titulo"]} no encontrado', 'error')
                return redirect(url_for('ver_carrito'))
            
            if libro.get('stock', 0) < item_carrito['cantidad']:
                flash(f'Stock insuficiente para {libro["nombre"]}', 'error')
                return redirect(url_for('ver_carrito'))
            
            items.append({
                'libro_id': str(libro['_id']),
                'titulo': libro['nombre'],
                'autor': libro.get('autor', ''),
                'genero': libro.get('genero', ''),
                'isbn': libro.get('isbn', ''),
                'cantidad': item_carrito['cantidad'],
                'precio_unitario': libro['precio'],
                'subtotal': item_carrito['subtotal']
            })
            
            subtotal_venta += item_carrito['subtotal']
            
            # Actualizar stock
            nuevo_stock = libro['stock'] - item_carrito['cantidad']
            coleccion_libros.update_one(
                {'_id': ObjectId(item_carrito['libro_id'])},
                {'$set': {'stock': nuevo_stock}}
            )
        
        # Calcular IVA y total
        iva_venta = calcular_iva(subtotal_venta)
        total_venta = subtotal_venta + iva_venta
        
        # Crear venta con información completa e IVA
        venta = {
            'cliente_id': session['cliente_id'],
            'cliente_nombre': session['cliente_nombre'],
            'cliente_email': session['cliente_email'],
            'items': items,
            'subtotal': subtotal_venta,
            'iva': iva_venta,
            'total': total_venta,
            'fecha_venta': datetime.now(),
            'estado': 'pendiente',
            'tipo': 'online'
        }
        
        resultado = coleccion_ventas.insert_one(venta)
        
        # Crear registro de seguimiento
        seguimiento = {
            'venta_id': str(resultado.inserted_id),
            'cliente_id': session['cliente_id'],
            'cliente_nombre': session['cliente_nombre'],
            'estado': 'pendiente',
            'fecha_pedido': datetime.now(),
            'ultima_actualizacion': datetime.now(),
            'comentarios': [{
                'fecha': datetime.now(),
                'mensaje': 'Pedido recibido',
                'usuario': 'Sistema'
            }]
        }
        coleccion_pedidos.insert_one(seguimiento)
        
        # Vaciar carrito después de la compra
        session['carrito'] = []
        session.modified = True
        
        flash(f'¡Compra realizada exitosamente! Total con IVA: ${total_venta:.2f}', 'success')
        return redirect(url_for('ver_compra', id=resultado.inserted_id))
        
    except Exception as e:
        flash(f'Error al procesar compra: {e}', 'error')
        return redirect(url_for('ver_carrito'))

# Añadir esta función que faltaba
@app.route('/comprar-directo', methods=['POST'])
@cliente_required
def comprar_directo():
    try:
        libro_id = request.form.get('libro_id')
        cantidad = int(request.form.get('cantidad', 1))
        
        libro = coleccion_libros.find_one({'_id': ObjectId(libro_id)})
        if not libro:
            flash('Libro no encontrado', 'error')
            return redirect(url_for('catalogo_cliente'))
        
        if libro.get('stock', 0) < cantidad:
            flash('Stock insuficiente', 'error')
            return redirect(url_for('catalogo_cliente'))
        
        # Crear venta con información completa
        subtotal = libro.get('precio', 0) * cantidad
        iva = calcular_iva(subtotal)
        total = subtotal + iva
        
        items = [{
            'libro_id': str(libro['_id']),
            'titulo': libro['nombre'],
            'autor': libro.get('autor', ''),
            'genero': libro.get('genero', ''),
            'isbn': libro.get('isbn', ''),
            'cantidad': cantidad,
            'precio_unitario': libro.get('precio', 0),
            'subtotal': subtotal
        }]
        
        venta = {
            'cliente_id': session['cliente_id'],
            'cliente_nombre': session['cliente_nombre'],
            'cliente_email': session['cliente_email'],
            'items': items,
            'subtotal': subtotal,
            'iva': iva,
            'total': total,
            'fecha_venta': datetime.now(),
            'estado': 'pendiente',
            'tipo': 'online'
        }
        
        # Actualizar stock
        nuevo_stock = libro['stock'] - cantidad
        coleccion_libros.update_one(
            {'_id': ObjectId(libro_id)},
            {'$set': {'stock': nuevo_stock}}
        )
        
        resultado = coleccion_ventas.insert_one(venta)
        
        # Crear registro de seguimiento
        seguimiento = {
            'venta_id': str(resultado.inserted_id),
            'cliente_id': session['cliente_id'],
            'cliente_nombre': session['cliente_nombre'],
            'estado': 'pendiente',
            'fecha_pedido': datetime.now(),
            'ultima_actualizacion': datetime.now(),
            'comentarios': [{
                'fecha': datetime.now(),
                'mensaje': 'Pedido recibido',
                'usuario': 'Sistema'
            }]
        }
        coleccion_pedidos.insert_one(seguimiento)
        
        flash(f'¡Compra realizada exitosamente! Total con IVA: ${total:.2f}', 'success')
        return redirect(url_for('ver_compra', id=resultado.inserted_id))
        
    except Exception as e:
        flash(f'Error al procesar compra: {e}', 'error')
        return redirect(url_for('catalogo_cliente'))

# ----------------- MIS COMPRAS CON CANCELACIONES -----------------

@app.route('/mis-compras')
@cliente_required
def mis_compras():
    try:
        ventas_cursor = coleccion_ventas.find({'cliente_id': session['cliente_id']})
        ventas = list(ventas_cursor)
        
        for venta in ventas:
            # Verificar cancelación
            cancelacion = coleccion_cancelaciones.find_one({'venta_id': str(venta['_id'])})
            venta['cancelada'] = cancelacion is not None
            venta['puede_cancelar'] = puede_cancelar_venta(venta['fecha_venta'])
        
        # Ordenar por fecha descendente
        ventas.sort(key=lambda x: x['fecha_venta'], reverse=True)
        
        return render_template('mis_compras.html', ventas=ventas)
    except Exception as e:
        flash(f'Error al cargar compras: {str(e)}', 'error')
        return render_template('mis_compras.html', ventas=[])

@app.route('/cancelar-mi-compra/<id>', methods=['POST'])
@cliente_required
def cancelar_mi_compra(id):
    try:
        venta = coleccion_ventas.find_one({
            '_id': ObjectId(id),
            'cliente_id': session['cliente_id']
        })
        
        if not venta:
            flash('Compra no encontrada', 'error')
            return redirect(url_for('mis_compras'))
        
        # Verificar si ya está cancelada
        cancelacion_existente = coleccion_cancelaciones.find_one({'venta_id': id})
        if cancelacion_existente:
            flash('Esta compra ya ha sido cancelada', 'error')
            return redirect(url_for('mis_compras'))
        
        # Verificar tiempo (15 minutos)
        if not puede_cancelar_venta(venta['fecha_venta']):
            flash('No se puede cancelar la compra después de 15 minutos', 'error')
            return redirect(url_for('mis_compras'))
        
        razon = request.form.get('razon', 'Cancelación solicitada por el cliente')
        
        # Crear registro de cancelación
        cancelacion = {
            'venta_id': id,
            'cliente_id': session['cliente_id'],
            'cliente_nombre': session['cliente_nombre'],
            'total_venta': venta['total'],
            'razon': razon,
            'cancelado_por': session['cliente_id'],
            'cancelado_por_nombre': session['cliente_nombre'],
            'fecha_cancelacion': datetime.now(),
            'fecha_venta_original': venta['fecha_venta']
        }
        
        # Devolver stock de libros
        for item in venta.get('items', []):
            libro_id = item['libro_id']
            cantidad = item['cantidad']
            
            libro = coleccion_libros.find_one({'_id': ObjectId(libro_id)})
            if libro:
                nuevo_stock = libro.get('stock', 0) + cantidad
                coleccion_libros.update_one(
                    {'_id': ObjectId(libro_id)},
                    {'$set': {'stock': nuevo_stock}}
                )
        
        # Guardar cancelación
        coleccion_cancelaciones.insert_one(cancelacion)
        
        # Marcar venta como cancelada
        coleccion_ventas.update_one(
            {'_id': ObjectId(id)},
            {'$set': {'estado': 'cancelada'}}
        )
        
        flash('Compra cancelada exitosamente. Stock devuelto a inventario.', 'success')
        return redirect(url_for('mis_compras'))
        
    except Exception as e:
        flash(f'Error al cancelar compra: {str(e)}', 'error')
        return redirect(url_for('mis_compras'))

# ----------------- COMPROBANTE PARA CLIENTES -----------------

@app.route('/mi-compra/<id>/comprobante')
@cliente_required
def comprobante_cliente(id):
    try:
        venta = coleccion_ventas.find_one({'_id': ObjectId(id), 'cliente_id': session['cliente_id']})
        if not venta:
            flash('Compra no encontrada', 'error')
            return redirect(url_for('mis_compras'))
        
        # Crear PDF
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # Configuración inicial
        pdf.setTitle(f"Comprobante de Compra - {venta['_id']}")
        
        # Encabezado
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(100, height - 50, "BIBLIOTECA DIGITAL")
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(100, height - 70, "COMPROBANTE DE COMPRA")
        pdf.line(100, height - 75, 500, height - 75)
        
        # Información de la compra
        y_position = height - 100
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "INFORMACIÓN DE LA COMPRA:")
        pdf.setFont("Helvetica", 10)
        y_position -= 15
        pdf.drawString(100, y_position, f"Folio: {str(venta['_id'])}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Fecha: {venta['fecha_venta'].strftime('%d/%m/%Y')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Hora: {venta['fecha_venta'].strftime('%H:%M:%S')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Estado: {venta.get('estado', 'Completada')}")
        
        # Información del cliente
        y_position -= 25
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "INFORMACIÓN DEL CLIENTE:")
        pdf.setFont("Helvetica", 10)
        y_position -= 15
        pdf.drawString(100, y_position, f"Nombre: {venta.get('cliente_nombre', 'N/A')}")
        y_position -= 15
        pdf.drawString(100, y_position, f"Email: {venta.get('cliente_email', 'N/A')}")
        
        # Tabla de productos
        y_position -= 30
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(100, y_position, "DETALLE DE PRODUCTOS:")
        
        # Encabezados de la tabla
        y_position -= 20
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(100, y_position, "Producto")
        pdf.drawString(300, y_position, "Cant.")
        pdf.drawString(350, y_position, "Precio Unit.")
        pdf.drawString(450, y_position, "Subtotal")
        
        y_position -= 10
        pdf.line(100, y_position, 500, y_position)
        y_position -= 10
        
        # Items de la venta
        pdf.setFont("Helvetica", 9)
        for item in venta.get('items', []):
            if y_position < 150:  # Nueva página si es necesario
                pdf.showPage()
                y_position = height - 50
                pdf.setFont("Helvetica", 9)
            
            # Título del libro
            titulo = item['titulo']
            if len(titulo) > 40:
                titulo = titulo[:37] + "..."
            
            pdf.drawString(100, y_position, titulo)
            pdf.drawString(300, y_position, str(item['cantidad']))
            pdf.drawString(350, y_position, f"${item['precio_unitario']:.2f}")
            pdf.drawString(450, y_position, f"${item['subtotal']:.2f}")
            
            y_position -= 20
        
        # Línea separadora
        y_position -= 10
        pdf.line(100, y_position, 500, y_position)
        
        # Totales
        subtotal = venta.get('subtotal', 0)
        iva = venta.get('iva', 0)
        total = venta.get('total', 0)
        
        y_position -= 20
        pdf.setFont("Helvetica", 10)
        pdf.drawString(350, y_position, f"Subtotal: ${subtotal:.2f}")
        y_position -= 15
        pdf.drawString(350, y_position, f"IVA (16%): ${iva:.2f}")
        y_position -= 15
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(350, y_position, f"TOTAL: ${total:.2f}")
        
        # Pie de página con agradecimiento
        y_position -= 40
        pdf.setFont("Helvetica-Oblique", 10)
        pdf.drawString(100, y_position, "¡Gracias por su compra en Biblioteca Digital!")
        y_position -= 15
        pdf.drawString(100, y_position, "Esperamos volver a servirle pronto.")
        
        pdf.save()
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"comprobante_compra_{id}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        return f"Error al generar comprobante: {e}", 500

# ----------------- VER COMPRA -----------------

@app.route('/mi-compra/<id>')
@cliente_required
def ver_compra(id):
    try:
        venta = coleccion_ventas.find_one({'_id': ObjectId(id), 'cliente_id': session['cliente_id']})
        if not venta:
            flash('Compra no encontrada', 'error')
            return redirect(url_for('mis_compras'))
        
        return render_template('ver_compra.html', venta=venta)
    except Exception as e:
        flash(f'Error al cargar compra: {e}', 'error')
        return redirect(url_for('mis_compras'))

# ----------------- REPORTE DE VENTAS EN PDF -----------------

@app.route('/reporte-ventas-pdf')
@login_required
def reporte_ventas_pdf():
    try:
        tipo = request.args.get('tipo', 'dia')
        fecha_str = request.args.get('fecha', '')
        fecha_inicio = request.args.get('inicio', '')
        fecha_fin = request.args.get('fin', '')
        
        # Construir consulta según el tipo de reporte
        query = {}
        
        if tipo == 'dia' and fecha_str:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d')
            query['fecha_venta'] = {
                '$gte': fecha,
                '$lt': fecha + timedelta(days=1)
            }
        elif tipo == 'mes' and fecha_str:
            fecha = datetime.strptime(fecha_str, '%Y-%m')
            next_month = fecha.replace(day=28) + timedelta(days=4)
            next_month = next_month.replace(day=1)
            query['fecha_venta'] = {
                '$gte': fecha,
                '$lt': next_month
            }
        elif tipo == 'anio' and fecha_str:
            año = int(fecha_str)
            query['fecha_venta'] = {
                '$gte': datetime(año, 1, 1),
                '$lt': datetime(año + 1, 1, 1)
            }
        elif tipo == 'personalizado' and fecha_inicio and fecha_fin:
            inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d')
            fin = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
            query['fecha_venta'] = {
                '$gte': inicio,
                '$lt': fin
            }
        
        # Obtener ventas filtradas
        ventas = list(coleccion_ventas.find(query).sort('fecha_venta', -1))
        
        # Crear PDF
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []
        
        styles = getSampleStyleSheet()
        
        # Título del reporte
        titulo = f"Reporte de Ventas - {tipo.capitalize()}"
        if fecha_str:
            titulo += f" - {fecha_str}"
        elements.append(Paragraph(titulo, styles['Title']))
        elements.append(Spacer(1, 12))
        
        # Estadísticas
        total_ventas = len(ventas)
        total_ingresos = sum(venta.get('total', 0) for venta in ventas)
        
        elements.append(Paragraph(f"Total de Ventas: {total_ventas}", styles['Normal']))
        elements.append(Paragraph(f"Ingresos Totales: ${total_ingresos:.2f}", styles['Normal']))
        elements.append(Spacer(1, 12))
        
        # Tabla de ventas
        if ventas:
            data = [['Folio', 'Cliente', 'Fecha', 'Total', 'Tipo']]
            
            for venta in ventas:
                data.append([
                    str(venta.get('_id', ''))[:8] + '...',
                    venta.get('cliente_nombre', ''),
                    venta.get('fecha_venta', datetime.now()).strftime('%d/%m/%Y %H:%M'),
                    f"${venta.get('total', 0):.2f}",
                    venta.get('tipo', '')
                ])
            
            table = Table(data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            elements.append(table)
        else:
            elements.append(Paragraph("No hay ventas en el período seleccionado", styles['Normal']))
        
        # Generar PDF
        doc.build(elements)
        
        buffer.seek(0)
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=reporte_ventas_{tipo}_{fecha_str}.pdf'
        
        return response
        
    except Exception as e:
        return f"Error al generar reporte: {str(e)}", 500

# ----------------- REPORTES DE VENTAS -----------------

@app.route('/reportes')
@login_required
def reportes_ventas():
    try:
        # Obtener parámetros de fecha
        periodo = request.args.get('periodo', 'hoy')
        
        hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        if periodo == 'hoy':
            fecha_inicio = hoy
            fecha_fin = datetime.now()
            titulo_periodo = "Hoy"
        elif periodo == 'semana':
            fecha_inicio = hoy - timedelta(days=hoy.weekday())
            fecha_fin = datetime.now()
            titulo_periodo = "Esta Semana"
        elif periodo == 'mes':
            fecha_inicio = hoy.replace(day=1)
            fecha_fin = datetime.now()
            titulo_periodo = "Este Mes"
        elif periodo == 'año':
            fecha_inicio = hoy.replace(month=1, day=1)
            fecha_fin = datetime.now()
            titulo_periodo = "Este Año"
        else:
            fecha_inicio = hoy
            fecha_fin = datetime.now()
            titulo_periodo = "Hoy"
        
        # Consultar ventas del período
        ventas_cursor = coleccion_ventas.find({
            'fecha_venta': {'$gte': fecha_inicio, '$lte': fecha_fin}
        }).sort('fecha_venta', -1)
        
        ventas = list(ventas_cursor)
        
        # Calcular estadísticas
        total_ventas = len(ventas)
        total_ingresos = sum(venta.get('total', 0) for venta in ventas)
        total_iva = sum(venta.get('iva', 0) for venta in ventas)
        total_subtotal = sum(venta.get('subtotal', 0) for venta in ventas)
        
        # Ventas por tipo
        ventas_online = len([v for v in ventas if v.get('tipo') == 'online'])
        ventas_presencial = len([v for v in ventas if v.get('tipo') == 'presencial'])
        
        # Top productos más vendidos
        productos_vendidos = {}
        for venta in ventas:
            for item in venta.get('items', []):
                producto_id = item.get('libro_id')
                if producto_id not in productos_vendidos:
                    productos_vendidos[producto_id] = {
                        'titulo': item.get('titulo'),
                        'cantidad': 0,
                        'total': 0
                    }
                productos_vendidos[producto_id]['cantidad'] += item.get('cantidad', 0)
                productos_vendidos[producto_id]['total'] += item.get('subtotal', 0)
        
        top_productos = sorted(productos_vendidos.values(), key=lambda x: x['cantidad'], reverse=True)[:10]
        
        # Ventas por día (para gráfico)
        ventas_por_dia = {}
        for venta in ventas:
            fecha = venta['fecha_venta'].strftime('%Y-%m-%d')
            if fecha not in ventas_por_dia:
                ventas_por_dia[fecha] = 0
            ventas_por_dia[fecha] += venta.get('total', 0)
        
        # Preparar datos para el gráfico
        fechas = sorted(ventas_por_dia.keys())
        montos = [ventas_por_dia[fecha] for fecha in fechas]
        
        return render_template('reportes.html',
                             ventas=ventas,
                             total_ventas=total_ventas,
                             total_ingresos=total_ingresos,
                             total_iva=total_iva,
                             total_subtotal=total_subtotal,
                             ventas_online=ventas_online,
                             ventas_presencial=ventas_presencial,
                             top_productos=top_productos,
                             fechas=fechas,
                             montos=montos,
                             periodo=periodo,
                             titulo_periodo=titulo_periodo,
                             fecha_inicio=fecha_inicio.strftime('%d/%m/%Y'),
                             fecha_fin=fecha_fin.strftime('%d/%m/%Y'))
                             
    except Exception as e:
        flash(f'Error al generar reportes: {str(e)}', 'error')
        return render_template('reportes.html', ventas=[], total_ventas=0, total_ingresos=0)

@app.route('/reporte-completo')
@login_required
def reporte_completo():
    try:
        # Obtener parámetros de fecha
        fecha_inicio_str = request.args.get('fecha_inicio')
        fecha_fin_str = request.args.get('fecha_fin')
        
        if fecha_inicio_str and fecha_fin_str:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d')
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            titulo_periodo = f"Del {fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}"
        else:
            # Por defecto, último mes
            fecha_fin = datetime.now()
            fecha_inicio = fecha_fin - timedelta(days=30)
            titulo_periodo = "Últimos 30 días"
        
        # Consultar ventas del período
        ventas_cursor = coleccion_ventas.find({
            'fecha_venta': {'$gte': fecha_inicio, '$lte': fecha_fin}
        }).sort('fecha_venta', -1)
        
        ventas = list(ventas_cursor)
        
        # Calcular estadísticas
        total_ventas = len(ventas)
        total_ingresos = sum(venta.get('total', 0) for venta in ventas)
        total_iva = sum(venta.get('iva', 0) for venta in ventas)
        total_subtotal = sum(venta.get('subtotal', 0) for venta in ventas)
        
        return render_template('reporte_completo.html',
                             ventas=ventas,
                             total_ventas=total_ventas,
                             total_ingresos=total_ingresos,
                             total_iva=total_iva,
                             total_subtotal=total_subtotal,
                             titulo_periodo=titulo_periodo,
                             fecha_inicio=fecha_inicio.strftime('%Y-%m-%d'),
                             fecha_fin=fecha_fin.strftime('%Y-%m-%d'))
                             
    except Exception as e:
        flash(f'Error al generar reporte completo: {str(e)}', 'error')
        return render_template('reporte_completo.html', ventas=[], total_ventas=0, total_ingresos=0)

# ----------------- INICIALIZACIÓN -----------------

if __name__ == '__main__':
    inicializar_datos()
    app.run(debug=True, host='0.0.0.0', port=5000)