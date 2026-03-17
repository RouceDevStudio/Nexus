FROM node:22-slim

# Instalar Python3 - queda en /usr/bin/python3 siempre
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias Node
COPY package*.json ./
RUN npm install --legacy-peer-deps

# Instalar dependencias Python
COPY requirements.txt ./
RUN pip3 install -r requirements.txt --break-system-packages

# Copiar todo el proyecto
COPY . .

EXPOSE 3000

CMD ["node", "index.js"]
