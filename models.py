# models.py
from datetime import datetime
from flask import current_app
from werkzeug.security import generate_password_hash, check_password_hash
import os
from bson import ObjectId

# Si usas Flask-PyMongo (probable)
from flask_pymongo import PyMongo
from bson.objectid import ObjectId

class Libro:
    def __init__(self, nombre, autor, genero, precio, stock, isbn, anio_publicacion, 
                 descripcion="", imagen_url="", fecha_creacion=None):
        self.nombre = nombre
        self.autor = autor
        self.genero = genero
        self.precio = float(precio)
        self.stock = int(stock)
        self.isbn = isbn
        self.anio_publicacion = int(anio_publicacion)
        self.descripcion = descripcion
        self.imagen_url = imagen_url or self.generar_imagen_por_defecto()
        self.fecha_creacion = fecha_creacion or datetime.utcnow()
    
    def generar_imagen_por_defecto(self):
        # Imágenes por defecto basadas en género
        generos_imagenes = {
            'Ficción': 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c',
            'Ciencia Ficción': 'https://images.unsplash.com/photo-1532012197267-da84d127e765',
            'Romance': 'https://images.unsplash.com/photo-1512820790803-83ca734da794',
            'Terror': 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d',
            'Fantasía': 'https://images.unsplash.com/photo-1513475382585-d06e58bcb0e0',
            'Aventura': 'https://images.unsplash.com/photo-1531901599638-a88c5bc9f03d',
            'Clásico': 'https://images.unsplash.com/photo-1541963463532-d68292c34b19',
            'Misterio': 'https://images.unsplash.com/photo-1512820790803-83ca734da794',
            'Drama': 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c'
        }
        
        for genero_key in generos_imagenes:
            if genero_key.lower() in self.genero.lower():
                return f"{generos_imagenes[genero_key]}?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80"
        
        # Imagen por defecto general
        return "https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80"
    
    def to_dict(self):
        return {
            'nombre': self.nombre,
            'autor': self.autor,
            'genero': self.genero,
            'precio': self.precio,
            'stock': self.stock,
            'isbn': self.isbn,
            'anio_publicacion': self.anio_publicacion,
            'descripcion': self.descripcion,
            'imagen_url': self.imagen_url,
            'fecha_creacion': self.fecha_creacion
        }
    
    @staticmethod
    def from_dict(data):
        libro = Libro(
            nombre=data.get('nombre'),
            autor=data.get('autor'),
            genero=data.get('genero'),
            precio=data.get('precio', 0),
            stock=data.get('stock', 0),
            isbn=data.get('isbn'),
            anio_publicacion=data.get('anio_publicacion'),
            descripcion=data.get('descripcion', ''),
            imagen_url=data.get('imagen_url', ''),
            fecha_creacion=data.get('fecha_creacion')
        )
        if '_id' in data:
            libro.id = str(data['_id'])
        return libro

class Usuario:
    def __init__(self, nombre, email, password, rol='empleado', telefono='', direccion=''):
        self.nombre = nombre
        self.email = email
        self.password_hash = generate_password_hash(password)
        self.rol = rol
        self.telefono = telefono
        self.direccion = direccion
        self.fecha_registro = datetime.utcnow()
        self.activo = True
    
    def to_dict(self):
        return {
            'nombre': self.nombre,
            'email': self.email,
            'password_hash': self.password_hash,
            'rol': self.rol,
            'telefono': self.telefono,
            'direccion': self.direccion,
            'fecha_registro': self.fecha_registro,
            'activo': self.activo
        }
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Cliente:
    def __init__(self, nombre, email, telefono='', direccion=''):
        self.nombre = nombre
        self.email = email
        self.telefono = telefono
        self.direccion = direccion
        self.fecha_registro = datetime.utcnow()
    
    def to_dict(self):
        return {
            'nombre': self.nombre,
            'email': self.email,
            'telefono': self.telefono,
            'direccion': self.direccion,
            'fecha_registro': self.fecha_registro
        }

class Venta:
    def __init__(self, cliente_id, usuario_id, items, total, iva=0.16, tipo='presencial', estado='completada'):
        self.cliente_id = cliente_id
        self.usuario_id = usuario_id
        self.items = items  # Lista de {libro_id, cantidad, precio_unitario, subtotal}
        self.subtotal = total / (1 + iva)
        self.iva = self.subtotal * iva
        self.total = total
        self.tipo = tipo
        self.estado = estado
        self.fecha_venta = datetime.utcnow()
        self.cancelada = False
        self.razon_cancelacion = ''
    
    def to_dict(self):
        return {
            'cliente_id': self.cliente_id,
            'usuario_id': self.usuario_id,
            'items': self.items,
            'subtotal': self.subtotal,
            'iva': self.iva,
            'total': self.total,
            'tipo': self.tipo,
            'estado': self.estado,
            'fecha_venta': self.fecha_venta,
            'cancelada': self.cancelada,
            'razon_cancelacion': self.razon_cancelacion
        }

# Configuración para subir imágenes
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
UPLOAD_FOLDER = 'static/uploads/libros'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_image(file, libro_id):
    if file and allowed_file(file.filename):
        filename = f"libro_{libro_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        return f"/{filepath}"
    return None