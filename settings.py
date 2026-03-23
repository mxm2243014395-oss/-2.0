import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = 'your-secret-key-here'

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'restaurant',
]




DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'smart_restaurant',      
        'USER': 'root',                 
        'PASSWORD': '123456',       
        'HOST': '127.0.0.1',            
        'PORT': '3306',               
        'OPTIONS': {
            'charset': 'utf8mb4',
        }
    }
}

TIME_ZONE = 'Asia/Shanghai'

USE_TZ = True

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

ROOT_URLCONF = 'urls'

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

WSGI_APPLICATION = 'wsgi.application'

LANGUAGE_CODE = 'zh-hans'

USE_I18N = True

USE_L10N = True

USE_TZ = True

# 告诉 Django：登录成功后，跳转到大屏页
LOGIN_REDIRECT_URL = '/dashboard/'

# 告诉 Django：退出登录后，跳回首页（登录页）
LOGOUT_REDIRECT_URL = '/'

# 告诉 Django：如果有未登录的访客想强行访问内部网页，全部踢回首页（登录页）
LOGIN_URL = '/'