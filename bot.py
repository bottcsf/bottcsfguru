import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import Optional, Dict, List
import asyncio
from pathlib import Path

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# ───────────────────────────────────────────
# CONFIGURAÇÃO
# ───────────────────────────────────────────
ADMIN_ROLE_IDS = [
    1492378748610412575,
    1495428206264713308,
    1491081676158275615,
    1491436528725917888,
]
DATA_FILE = "data.json"
BACKUP_DIR = "backups"
BANNER_LIGA = None

# Cache em memória (reduz leitura de arquivo)
_data_cache: Optional[Dict] = None
_cache_timestamp: Optional[datetime] = None
CACHE_DURATION = timedelta(seconds=30)

# Dicionário para cooldowns
cooldowns_obter = {}
cooldowns_daily = {}

# ───────────────────────────────────────────
# NORMALIZAÇÃO DE POSIÇÕES
# ───────────────────────────────────────────
POSICAO_NORMALIZE = {
    # Inglês → Português
    "GK": "GOL",
    "CB": "ZAG",
    "LB": "LE",
    "RB": "LD",
    "CDM": "VOL",
    "CM": "MEI",
    "CAM": "MEI",
    "LM": "MEI",
    "RM": "MEI",
    "LW": "ATA",
    "RW": "ATA",
    "ST": "ATA",
    "CF": "ATA",
    # Português (mantém)
    "GOL": "GOL",
    "ZAG": "ZAG",
    "LD": "LD",
    "LE": "LE",
    "VOL": "VOL",
    "MEI": "MEI",
    "ATA": "ATA"
}

POSICAO_FULL = {
    "GOL": "Goleiro",
    "ZAG": "Zagueiro",
    "LD": "Lateral Direito",
    "LE": "Lateral Esquerdo",
    "VOL": "Volante",
    "MEI": "Meia",
    "ATA": "Atacante"
}

def normalizar_posicao(pos: str) -> str:
    """Normaliza posição para padrão português"""
    pos_upper = pos.upper().strip()
    return POSICAO_NORMALIZE.get(pos_upper, "MEI")

# ───────────────────────────────────────────
# SISTEMA DE BACKUP
# ───────────────────────────────────────────
def criar_backup():
    """Cria backup do data.json"""
    try:
        if not os.path.exists(DATA_FILE):
            return
        
        Path(BACKUP_DIR).mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{BACKUP_DIR}/data_backup_{timestamp}.json"
        
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            dados = json.load(f)
        
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        
        # Mantém apenas últimos 10 backups
        backups = sorted(Path(BACKUP_DIR).glob("data_backup_*.json"))
        if len(backups) > 10:
            for backup in backups[:-10]:
                backup.unlink()
        
        print(f"✅ Backup criado: {backup_file}")
    except Exception as e:
        print(f"⚠️ Erro ao criar backup: {e}")

# ───────────────────────────────────────────
# VALIDAÇÃO E CORREÇÃO DE DADOS
# ───────────────────────────────────────────
def validar_jogador(jogador: dict) -> dict:
    """Valida e corrige dados de um jogador"""
    campos_obrigatorios = {
        "nome": "Sem Nome",
        "posicao": "MEI",
        "overall": 50,
        "clube": "Sem Clube",
        "preco": 1000,
        "imagem": None
    }
    
    # Garante campos obrigatórios
    for campo, padrao in campos_obrigatorios.items():
        if campo not in jogador or jogador[campo] is None:
            jogador[campo] = padrao
    
    # Normaliza posição
    jogador["posicao"] = normalizar_posicao(jogador["posicao"])
    
    # Valida overall
    try:
        jogador["overall"] = max(1, min(99, int(jogador["overall"])))
    except:
        jogador["overall"] = 50
    
    # Valida preço
    try:
        jogador["preco"] = max(1000, int(jogador["preco"]))
    except:
        jogador["preco"] = 1000
    
    return jogador

def remover_duplicatas_elenco(elenco: List[dict]) -> List[dict]:
    """Remove jogadores duplicados do elenco (mantém primeiro)"""
    vistos = set()
    elenco_limpo = []
    
    for jogador in elenco:
        chave = f"{jogador['nome'].lower()}_{jogador['overall']}"
        if chave not in vistos:
            vistos.add(chave)
            elenco_limpo.append(validar_jogador(jogador))
    
    return elenco_limpo

def validar_e_corrigir_dados(dados: dict) -> dict:
    """Valida e corrige todo o data.json"""
    # Garante estrutura básica
    if "jogadores_disponiveis" not in dados:
        dados["jogadores_disponiveis"] = []
    if "membros" not in dados:
        dados["membros"] = {}
    
    # Valida jogadores disponíveis
    jogadores_validos = []
    for jogador in dados["jogadores_disponiveis"]:
        jogadores_validos.append(validar_jogador(jogador))
    dados["jogadores_disponiveis"] = jogadores_validos
    
    # Valida membros
    for user_id, membro in dados["membros"].items():
        # Garante campos obrigatórios
        if "saldo" not in membro:
            membro["saldo"] = 1000
        if "time_nome" not in membro:
            membro["time_nome"] = None
        if "time_sigla" not in membro:
            membro["time_sigla"] = None
        if "elenco" not in membro:
            membro["elenco"] = []
        if "titulares" not in membro:
            membro["titulares"] = []
        
        # Remove duplicatas
        membro["elenco"] = remover_duplicatas_elenco(membro["elenco"])
        membro["titulares"] = remover_duplicatas_elenco(membro["titulares"])
    
    return dados

# ───────────────────────────────────────────
# SISTEMA DE CACHE INTELIGENTE
# ───────────────────────────────────────────
def carregar_dados(forcar_reload: bool = False) -> dict:
    """Carrega dados com cache em memória"""
    global _data_cache, _cache_timestamp
    
    agora = datetime.now()
    
    # Usa cache se disponível e válido
    if not forcar_reload and _data_cache and _cache_timestamp:
        if agora - _cache_timestamp < CACHE_DURATION:
            return _data_cache.copy()
    
    # Carrega do arquivo
    if not os.path.exists(DATA_FILE):
        dados = {"jogadores_disponiveis": [], "membros": {}}
    else:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except json.JSONDecodeError:
            print("⚠️ Erro ao ler JSON! Criando backup e resetando...")
            criar_backup()
            dados = {"jogadores_disponiveis": [], "membros": {}}
    
    # Valida e corrige
    dados = validar_e_corrigir_dados(dados)
    
    # Atualiza cache
    _data_cache = dados.copy()
    _cache_timestamp = agora
    
    return dados

def salvar_dados(dados: dict):
    """Salva dados e atualiza cache"""
    global _data_cache, _cache_timestamp
    
    # Valida antes de salvar
    dados = validar_e_corrigir_dados(dados)
    
    # Salva no arquivo
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    
    # Atualiza cache
    _data_cache = dados.copy()
    _cache_timestamp = datetime.now()

def invalidar_cache():
    """Força recarregamento do cache"""
    global _data_cache, _cache_timestamp
    _data_cache = None
    _cache_timestamp = None

# ───────────────────────────────────────────
# SISTEMA DE CHANCE MELHORADO
# ───────────────────────────────────────────
def calcular_peso_raridade(jogador: dict) -> float:
    """
    Calcula peso de raridade (quanto MENOR, mais raro).
    Sistema balanceado baseado em overall e preço.
    """
    overall = jogador.get("overall", 50)
    preco = jogador.get("preco", 1000)
    
    # Sistema exponencial de raridade por overall
    if overall >= 95:
        peso_ovr = 0.1  # Ultra raro
    elif overall >= 90:
        peso_ovr = 0.5  # Muito raro
    elif overall >= 85:
        peso_ovr = 2.0  # Raro
    elif overall >= 80:
        peso_ovr = 5.0  # Incomum
    elif overall >= 75:
        peso_ovr = 10.0  # Comum
    elif overall >= 70:
        peso_ovr = 15.0  # Muito comum
    else:
        peso_ovr = 25.0  # Extremamente comum
    
    # Fator de preço (normalizado)
    if preco >= 50_000_000:
        peso_preco = 0.1
    elif preco >= 10_000_000:
        peso_preco = 0.3
    elif preco >= 5_000_000:
        peso_preco = 0.8
    elif preco >= 2_000_000:
        peso_preco = 2.0
    elif preco >= 1_000_000:
        peso_preco = 4.0
    elif preco >= 500_000:
        peso_preco = 8.0
    else:
        peso_preco = 15.0
    
    # Peso final (média ponderada: 70% overall, 30% preço)
    peso_final = (peso_ovr * 0.7) + (peso_preco * 0.3)
    
    return peso_final

def sortear_jogador_ponderado(jogadores: list) -> dict:
    """Sorteia jogador com sistema de pesos balanceado"""
    if not jogadores:
        return None
    
    # Calcula pesos
    pesos = [calcular_peso_raridade(j) for j in jogadores]
    
    # Sorteia (weights maiores = mais chance)
    jogador = random.choices(jogadores, weights=pesos, k=1)[0]
    
    return jogador

def calcular_raridade(jogador: dict) -> str:
    """Retorna classificação de raridade"""
    peso = calcular_peso_raridade(jogador)
    overall = jogador.get("overall", 50)
    
    if overall >= 95 or peso <= 0.5:
        return "🔴 LENDÁRIO"
    elif overall >= 90 or peso <= 1.5:
        return "🟠 ÉPICO"
    elif overall >= 85 or peso <= 4:
        return "🟣 RARO"
    elif overall >= 80 or peso <= 8:
        return "🔵 INCOMUM"
    else:
        return "🟢 COMUM"

def calcular_chance_percentual(jogador: dict, todos_jogadores: list) -> float:
    """Calcula chance aproximada em % de obter o jogador"""
    if not todos_jogadores:
        return 0.0
    
    pesos = [calcular_peso_raridade(j) for j in todos_jogadores]
    peso_jogador = calcular_peso_raridade(jogador)
    soma_pesos = sum(pesos)
    
    if soma_pesos == 0:
        return 0.0
    
    chance = (peso_jogador / soma_pesos) * 100
    return round(chance, 2)

# ───────────────────────────────────────────
# UTILITÁRIOS
# ───────────────────────────────────────────
def get_membro(dados, user_id: str):
    """Obtém ou cria dados do membro"""
    if user_id not in dados["membros"]:
        dados["membros"][user_id] = {
            "saldo": 1000,
            "time_nome": None,
            "time_sigla": None,
            "elenco": [],
            "titulares": []
        }
    return dados["membros"][user_id]

def is_admin(interaction: discord.Interaction) -> bool:
    """Verifica se usuário é admin"""
    return any(r.id in ADMIN_ROLE_IDS for r in interaction.user.roles)

def fmt_reais(valor) -> str:
    """Formata valor em reais"""
    return f"R$ {int(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def cor_por_overall(overall: int) -> int:
    """Retorna cor hex baseada no overall"""
    if overall >= 95:
        return 0xff4500  # Vermelho
    if overall >= 90:
        return 0xffd700  # Ouro
    if overall >= 85:
        return 0xb44fea  # Roxo
    if overall >= 80:
        return 0x1e90ff  # Azul
    if overall >= 70:
        return 0x2ecc71  # Verde
    return 0x95a5a6  # Cinza

def medalha_overall(overall: int) -> str:
    """Retorna medalha do overall"""
    if overall >= 99:
        return "👑 LENDÁRIO"
    if overall >= 90:
        return "🏆 ELITE"
    if overall >= 85:
        return "💎 RARO"
    if overall >= 80:
        return "⭐ BOM"
    if overall >= 70:
        return "🥈 PRATA"
    return "🥉 BRONZE"

def estrelas_overall(overall: int) -> str:
    """Retorna estrelas do overall"""
    if overall >= 90:
        return "★★★★★"
    if overall >= 80:
        return "★★★★☆"
    if overall >= 70:
        return "★★★☆☆"
    if overall >= 60:
        return "★★☆☆☆"
    return "★☆☆☆☆"

# ───────────────────────────────────────────
# VIEW PARA LISTA DE JOGADORES (COMPRA)
# ───────────────────────────────────────────
class ListaJogadoresView(discord.ui.View):
    def __init__(self, user_id: int, jogadores: list, pagina: int = 0):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.jogadores = sorted(jogadores, key=lambda j: j["overall"], reverse=True)
        self.pagina = pagina
        self.itens_por_pagina = 10
        self.total_paginas = max(1, (len(self.jogadores) - 1) // self.itens_por_pagina + 1)
        
        self.atualizar_botoes()
    
    def atualizar_botoes(self):
        self.clear_items()
        
        # Botões de navegação
        if self.pagina > 0:
            self.add_item(BotaoAnterior())
        
        if self.pagina < self.total_paginas - 1:
            self.add_item(BotaoProximo())
        
        # Botões de jogadores
        inicio = self.pagina * self.itens_por_pagina
        fim = min(inicio + self.itens_por_pagina, len(self.jogadores))
        
        for i in range(inicio, fim):
            jogador = self.jogadores[i]
            self.add_item(BotaoJogador(jogador, i - inicio))
    
    def get_embed(self):
        dados = carregar_dados()
        membro = get_membro(dados, str(self.user_id))
        saldo = membro.get("saldo", 0)
        
        embed = discord.Embed(
            title="🏪 Mercado de Transferências",
            description=f"**Seu saldo:** {fmt_reais(saldo)}\n\nSelecione um jogador para comprar:",
            color=0x1e90ff
        )
        
        inicio = self.pagina * self.itens_por_pagina
        fim = min(inicio + self.itens_por_pagina, len(self.jogadores))
        
        for i in range(inicio, fim):
            jogador = self.jogadores[i]
            pos_full = POSICAO_FULL.get(jogador["posicao"], jogador["posicao"])
            pode_comprar = "✅" if saldo >= jogador["preco"] else "❌"
            raridade = calcular_raridade(jogador)
            
            embed.add_field(
                name=f"{pode_comprar} {jogador['nome']} · {jogador['overall']} OVR",
                value=f"{pos_full} · {jogador['clube']}\n💰 {fmt_reais(jogador['preco'])} · {raridade}",
                inline=True
            )
        
        embed.set_footer(text=f"TCSF Guru · Página {self.pagina + 1}/{self.total_paginas} · {len(self.jogadores)} jogadores")
        return embed
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Esta lista não é sua.", ephemeral=True)
            return False
        return True

class BotaoAnterior(discord.ui.Button):
    def __init__(self):
        super().__init__(label="◀ Anterior", style=discord.ButtonStyle.secondary, row=0)
    
    async def callback(self, interaction: discord.Interaction):
        view: ListaJogadoresView = self.view
        view.pagina -= 1
        view.atualizar_botoes()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

class BotaoProximo(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Próximo ▶", style=discord.ButtonStyle.secondary, row=0)
    
    async def callback(self, interaction: discord.Interaction):
        view: ListaJogadoresView = self.view
        view.pagina += 1
        view.atualizar_botoes()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

class BotaoJogador(discord.ui.Button):
    def __init__(self, jogador: dict, posicao: int):
        self.jogador = jogador
        label = f"{jogador['nome'][:20]} · {fmt_reais(jogador['preco'])}"
        
        if jogador["overall"] >= 90:
            style = discord.ButtonStyle.success
        elif jogador["overall"] >= 80:
            style = discord.ButtonStyle.primary
        else:
            style = discord.ButtonStyle.secondary
        
        super().__init__(
            label=label,
            style=style,
            row=(posicao // 5) + 1
        )
    
    async def callback(self, interaction: discord.Interaction):
        dados = carregar_dados()
        user_id = str(interaction.user.id)
        membro = get_membro(dados, user_id)
        
        preco = self.jogador.get("preco", 0)
        saldo = membro.get("saldo", 0)
        
        if saldo < preco:
            embed = discord.Embed(
                title="💸 Saldo Insuficiente",
                description=f"Você não tem saldo suficiente para comprar **{self.jogador['nome']}**.",
                color=0xe74c3c
            )
            embed.add_field(name="Preço", value=fmt_reais(preco), inline=True)
            embed.add_field(name="Seu saldo", value=fmt_reais(saldo), inline=True)
            embed.add_field(name="Faltam", value=fmt_reais(preco - saldo), inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Verifica duplicata
        if any(j["nome"].lower() == self.jogador["nome"].lower() for j in membro.get("elenco", [])):
            await interaction.response.send_message(
                f"Você já tem **{self.jogador['nome']}** no seu elenco!",
                ephemeral=True
            )
            return
        
        # Realiza compra
        membro["saldo"] -= preco
        membro["elenco"].append(self.jogador)
        salvar_dados(dados)
        
        pos_full = POSICAO_FULL.get(self.jogador["posicao"], self.jogador["posicao"])
        
        embed = discord.Embed(
            title="✅ Transferência Concluída!",
            description=f"**{self.jogador['nome']}** foi contratado com sucesso!\n\n{medalha_overall(self.jogador['overall'])} · {estrelas_overall(self.jogador['overall'])}",
            color=0x2ecc71
        )
        embed.add_field(name="Posição", value=pos_full, inline=True)
        embed.add_field(name="Overall", value=f"**{self.jogador['overall']}**", inline=True)
        embed.add_field(name="Clube de origem", value=self.jogador["clube"], inline=True)
        embed.add_field(name="Valor pago", value=fmt_reais(preco), inline=True)
        embed.add_field(name="Novo saldo", value=fmt_reais(membro["saldo"]), inline=True)
        embed.add_field(name="Elenco", value=f"{len(membro['elenco'])} jogadores", inline=True)
        
        if self.jogador.get("imagem"):
            embed.set_thumbnail(url=self.jogador["imagem"])
        
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"TCSF Guru · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        
        await interaction.response.send_message(embed=embed)
        
        # Atualiza view
        view: ListaJogadoresView = self.view
        await interaction.message.edit(embed=view.get_embed())

# ───────────────────────────────────────────
# VIEW COM BOTÕES DO /obter
# ───────────────────────────────────────────
class BotoesObter(discord.ui.View):
    def __init__(self, user_id: int, jogador: dict):
        super().__init__(timeout=90)
        self.user_id = user_id
        self.jogador = jogador
        self.acao_realizada = False
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Esses botões não são seus.", ephemeral=True)
            return False
        return True
    
    @discord.ui.button(label="▲ Escalar como Titular", style=discord.ButtonStyle.success)
    async def promover_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.acao_realizada:
            await interaction.response.send_message("Você já realizou uma ação com este jogador.", ephemeral=True)
            return
        
        dados = carregar_dados()
        membro = get_membro(dados, str(self.user_id))
        titulares = membro.get("titulares", [])
        
        if any(j["nome"].lower() == self.jogador["nome"].lower() for j in titulares):
            await interaction.response.send_message(
                f"**{self.jogador['nome']}** já está entre os titulares.",
                ephemeral=True
            )
            return
        
        if len(titulares) >= 11:
            await interaction.response.send_message(
                "Você já tem 11 titulares. Remova um antes.",
                ephemeral=True
            )
            return
        
        titulares.append(self.jogador)
        membro["titulares"] = titulares
        salvar_dados(dados)
        
        self.acao_realizada = True
        for child in self.children:
            child.disabled = True
        button.label = "✓ Escalado!"
        await interaction.response.edit_message(view=self)
        
        embed = discord.Embed(
            title="Titular Confirmado",
            description=f"**{self.jogador['nome']}** entrou no time titular.\n{len(titulares)}/11 posições preenchidas.",
            color=0x2ecc71
        )
        if self.jogador.get("imagem"):
            embed.set_thumbnail(url=self.jogador["imagem"])
        embed.set_footer(text="TCSF Guru · Liga")
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="✕ Vender", style=discord.ButtonStyle.danger)
    async def vender_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.acao_realizada:
            await interaction.response.send_message("Você já realizou uma ação com este jogador.", ephemeral=True)
            return
        
        dados = carregar_dados()
        membro = get_membro(dados, str(self.user_id))
        elenco = membro.get("elenco", [])
        
        jogador_no_elenco = next(
            (j for j in elenco if j["nome"].lower() == self.jogador["nome"].lower()),
            None
        )
        
        if not jogador_no_elenco:
            await interaction.response.send_message("Jogador não encontrado no elenco.", ephemeral=True)
            return
        
        preco_venda = int(self.jogador.get("preco", 0) * 0.6)
        elenco.remove(jogador_no_elenco)
        membro["elenco"] = elenco
        membro["saldo"] = membro.get("saldo", 0) + preco_venda
        membro["titulares"] = [
            j for j in membro.get("titulares", [])
            if j["nome"].lower() != self.jogador["nome"].lower()
        ]
        salvar_dados(dados)
        
        self.acao_realizada = True
        for child in self.children:
            child.disabled = True
        button.label = "Vendido"
        await interaction.response.edit_message(view=self)
        
        embed = discord.Embed(
            title="Negociação Concluída",
            description=(
                f"**{self.jogador['nome']}** foi vendido pelo clube.\n\n"
                f"**Valor recebido:** {fmt_reais(preco_venda)} *(60% do valor de mercado)*\n"
                f"**Saldo atual:** {fmt_reais(membro['saldo'])}"
            ),
            color=0xe74c3c
        )
        embed.set_footer(text="TCSF Guru · Liga")
        await interaction.followup.send(embed=embed, ephemeral=True)

# ───────────────────────────────────────────
# VIEW SELECT MENU PARA SETAR JOGADOR
# ───────────────────────────────────────────
class SelectMembroView(discord.ui.View):
    def __init__(self, admin_id: int, jogador: dict):
        super().__init__(timeout=180)
        self.admin_id = admin_id
        self.jogador = jogador
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message("Apenas o administrador que executou o comando pode usar este menu.", ephemeral=True)
            return False
        return True
    
    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Selecione o membro que receberá o jogador",
        min_values=1,
        max_values=1
    )
    async def select_membro(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        membro_selecionado = select.values[0]
        
        dados = carregar_dados()
        user_id = str(membro_selecionado.id)
        membro_dados = get_membro(dados, user_id)
        
        if any(j["nome"].lower() == self.jogador["nome"].lower() for j in membro_dados.get("elenco", [])):
            await interaction.response.send_message(
                f"❌ **{membro_selecionado.display_name}** já possui **{self.jogador['nome']}** no elenco!",
                ephemeral=True
            )
            return
        
        membro_dados["elenco"].append(self.jogador)
        salvar_dados(dados)
        
        pos_full = POSICAO_FULL.get(self.jogador["posicao"], self.jogador["posicao"])
        
        embed = discord.Embed(
            title="✅ Jogador Setado com Sucesso!",
            description=f"**{self.jogador['nome']}** foi adicionado ao elenco de **{membro_selecionado.display_name}**.",
            color=0x2ecc71
        )
        embed.add_field(name="Jogador", value=self.jogador['nome'], inline=True)
        embed.add_field(name="Overall", value=f"{self.jogador['overall']}", inline=True)
        embed.add_field(name="Posição", value=pos_full, inline=True)
        embed.add_field(name="Clube", value=self.jogador['clube'], inline=True)
        embed.add_field(name="Valor", value=fmt_reais(self.jogador['preco']), inline=True)
        embed.add_field(name="Elenco Total", value=f"{len(membro_dados['elenco'])} jogadores", inline=True)
        
        if self.jogador.get("imagem"):
            embed.set_thumbnail(url=self.jogador["imagem"])
        
        embed.set_author(name=membro_selecionado.display_name, icon_url=membro_selecionado.display_avatar.url)
        embed.set_footer(text=f"Setado por {interaction.user.display_name} • {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        
        for child in self.children:
            child.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        try:
            notif_embed = discord.Embed(
                title="🎁 Novo Jogador Recebido!",
                description=f"Você recebeu **{self.jogador['nome']}** ({self.jogador['overall']} OVR) no seu elenco!",
                color=cor_por_overall(self.jogador["overall"])
            )
            notif_embed.set_footer(text="TCSF Guru · Liga")
            await membro_selecionado.send(embed=notif_embed)
        except:
            pass

# ───────────────────────────────────────────
# BOT
# ───────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

@bot.event
async def on_ready():
    # Valida e cria backup ao iniciar
    criar_backup()
    dados = carregar_dados(forcar_reload=True)
    salvar_dados(dados)
    
    await tree.sync()
    print(f"✅ Bot online como {bot.user}")
    print(f"📊 {len(dados['jogadores_disponiveis'])} jogadores disponíveis")
    print(f"👥 {len(dados['membros'])} membros registrados")
    print("🔧 Sistema de cache e validação ativo")

# ───────────────────────────────────────────
# COMANDOS
# ───────────────────────────────────────────

@tree.command(name="addplayer", description="[ADM] Adiciona um jogador ao banco")
@app_commands.describe(
    nome="Nome do jogador",
    posicao="Posição (GOL, ZAG, LD, LE, VOL, MEI, ATA ou GK, CB, etc)",
    overall="Overall do jogador (1-99)",
    clube="Clube do jogador",
    preco="Preço em reais",
    imagem="URL da imagem da carta do jogador"
)
async def addplayer(
    interaction: discord.Interaction,
    nome: str,
    posicao: str,
    overall: int,
    clube: str,
    preco: int,
    imagem: str = None
):
    if not is_admin(interaction):
        await interaction.response.send_message("Apenas administradores podem usar este comando.", ephemeral=True)
        return
    
    dados = carregar_dados()
    
    # Valida e cria jogador
    jogador = validar_jogador({
        "nome": nome,
        "posicao": posicao,
        "overall": overall,
        "clube": clube,
        "preco": preco,
        "imagem": imagem
    })
    
    dados["jogadores_disponiveis"].append(jogador)
    salvar_dados(dados)
    
    pos_full = POSICAO_FULL.get(jogador["posicao"], jogador["posicao"])
    raridade = calcular_raridade(jogador)
    todos = dados["jogadores_disponiveis"]
    chance = calcular_chance_percentual(jogador, todos)
    
    embed = discord.Embed(
        title=f"{jogador['nome']}",
        description=f"{medalha_overall(jogador['overall'])} · {estrelas_overall(jogador['overall'])}\n\nJogador adicionado ao banco da liga.",
        color=cor_por_overall(jogador['overall'])
    )
    embed.add_field(name="Posição", value=f"{pos_full} (`{jogador['posicao']}`)", inline=True)
    embed.add_field(name="Overall", value=f"{jogador['overall']}", inline=True)
    embed.add_field(name="Clube", value=clube, inline=True)
    embed.add_field(name="Valor de Mercado", value=fmt_reais(preco), inline=True)
    embed.add_field(name="Raridade", value=raridade, inline=True)
    embed.add_field(name="Chance /obter", value=f"~{chance}%", inline=True)
    embed.add_field(name="Total no banco", value=f"{len(todos)} jogadores", inline=False)
    
    if imagem:
        embed.set_image(url=imagem)
    
    embed.set_footer(text=f"TCSF Guru · ADM · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    await interaction.response.send_message(embed=embed)

@tree.command(name="comprar", description="Abre o mercado de transferências")
async def comprar(interaction: discord.Interaction):
    dados = carregar_dados()
    disponiveis = dados.get("jogadores_disponiveis", [])
    
    if not disponiveis:
        embed = discord.Embed(
            title="🏪 Mercado Vazio",
            description="Não há jogadores disponíveis para compra no momento.",
            color=0x95a5a6
        )
        embed.set_footer(text="TCSF Guru · Liga")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    view = ListaJogadoresView(interaction.user.id, disponiveis)
    embed = view.get_embed()
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@tree.command(name="obter", description="Sorteia um jogador do banco (cooldown: 20min)")
async def obter(interaction: discord.Interaction):
    user_id = interaction.user.id
    
    # Cooldown (exceto admins)
    if not is_admin(interaction):
        agora = datetime.now()
        if user_id in cooldowns_obter:
            ultimo_uso = cooldowns_obter[user_id]
            tempo_restante = timedelta(minutes=20) - (agora - ultimo_uso)
            
            if tempo_restante.total_seconds() > 0:
                minutos = int(tempo_restante.total_seconds() // 60)
                segundos = int(tempo_restante.total_seconds() % 60)
                
                embed = discord.Embed(
                    title="⏰ Cooldown Ativo",
                    description=f"Você precisa aguardar **{minutos}m {segundos}s** para usar `/obter` novamente.",
                    color=0xe67e22
                )
                embed.set_footer(text="TCSF Guru · Liga")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        
        cooldowns_obter[user_id] = agora
    
    dados = carregar_dados()
    disponiveis = dados.get("jogadores_disponiveis", [])
    
    if not disponiveis:
        embed = discord.Embed(
            title="Banco Vazio",
            description="Nenhum jogador disponível no momento.",
            color=0x95a5a6
        )
        embed.set_footer(text="TCSF Guru · Liga")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    user_id_str = str(interaction.user.id)
    membro = get_membro(dados, user_id_str)
    
    # Sorteia com sistema de raridade
    jogador = sortear_jogador_ponderado(disponiveis)
    raridade = calcular_raridade(jogador)
    chance = calcular_chance_percentual(jogador, disponiveis)
    
    membro["elenco"].append(jogador)
    salvar_dados(dados)
    
    pos_full = POSICAO_FULL.get(jogador["posicao"], jogador["posicao"])
    cor = cor_por_overall(jogador["overall"])
    
    embed = discord.Embed(
        title=f"{jogador['nome']}",
        description=(
            f"{medalha_overall(jogador['overall'])} · {estrelas_overall(jogador['overall'])}\n\n"
            f"{interaction.user.display_name} recebeu um novo reforço!\n"
            f"**Raridade:** {raridade} (chance ~{chance}%)\n\n"
            f"Use os botões abaixo para escalar ou vender."
        ),
        color=cor
    )
    embed.add_field(name="Posição", value=pos_full, inline=True)
    embed.add_field(name="Overall", value=f"{jogador['overall']}", inline=True)
    embed.add_field(name="Clube", value=jogador["clube"], inline=True)
    embed.add_field(name="Valor de Mercado", value=fmt_reais(jogador["preco"]), inline=True)
    embed.add_field(name="Valor de Venda", value=fmt_reais(jogador["preco"] * 0.6), inline=True)
    embed.add_field(name="Elenco", value=f"{len(membro['elenco'])} jogadores", inline=True)
    
    if jogador.get("imagem"):
        embed.set_image(url=jogador["imagem"])
    
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    embed.set_footer(text=f"TCSF Guru · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    view = BotoesObter(user_id=interaction.user.id, jogador=jogador)
    await interaction.response.send_message(embed=embed, view=view)

@tree.command(name="daily", description="Resgate R$ 200.000 diários (cooldown: 24h)")
async def daily(interaction: discord.Interaction):
    user_id = interaction.user.id
    agora = datetime.now()

    if user_id in cooldowns_daily:
        ultimo_uso = cooldowns_daily[user_id]
        tempo_restante = timedelta(hours=24) - (agora - ultimo_uso)

        if tempo_restante.total_seconds() > 0:
            horas = int(tempo_restante.total_seconds() // 3600)
            minutos = int((tempo_restante.total_seconds() % 3600) // 60)
            segundos = int(tempo_restante.total_seconds() % 60)

            embed = discord.Embed(
                title="⏰ Daily já resgatado!",
                description=f"Você já resgatou o seu daily hoje.\n\nVolte em **{horas}h {minutos}m {segundos}s**.",
                color=0xe67e22
            )
            embed.set_footer(text="TCSF Guru · Liga")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

    cooldowns_daily[user_id] = agora

    dados = carregar_dados()
    user_id_str = str(interaction.user.id)
    membro = get_membro(dados, user_id_str)

    bonus = 200_000
    membro["saldo"] = membro.get("saldo", 0) + bonus
    salvar_dados(dados)

    embed = discord.Embed(
        title="💰 Daily Resgatado!",
        description=f"Você recebeu **{fmt_reais(bonus)}** na sua carteira!\n\nVolte amanhã para resgatar novamente.",
        color=0xffd700
    )
    embed.add_field(name="Valor recebido", value=fmt_reais(bonus), inline=True)
    embed.add_field(name="Novo saldo", value=fmt_reais(membro["saldo"]), inline=True)
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    embed.set_footer(text=f"TCSF Guru · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    await interaction.response.send_message(embed=embed)

@tree.command(name="promover", description="Promove um jogador para titular")
@app_commands.describe(nome="Nome do jogador")
async def promover(interaction: discord.Interaction, nome: str):
    dados = carregar_dados()
    user_id = str(interaction.user.id)
    membro = get_membro(dados, user_id)
    
    elenco = membro.get("elenco", [])
    titulares = membro.get("titulares", [])
    
    jogador = next((j for j in elenco if j["nome"].lower() == nome.lower()), None)
    if not jogador:
        embed = discord.Embed(
            title="Jogador não encontrado",
            description=f"{nome} não está no seu elenco.",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    if any(j["nome"].lower() == nome.lower() for j in titulares):
        await interaction.response.send_message(f"{nome} já está entre os titulares.", ephemeral=True)
        return
    
    if len(titulares) >= 11:
        await interaction.response.send_message("Você já tem 11 titulares. Remova um antes.", ephemeral=True)
        return
    
    titulares.append(jogador)
    membro["titulares"] = titulares
    salvar_dados(dados)
    
    pos_full = POSICAO_FULL.get(jogador["posicao"], jogador["posicao"])
    
    embed = discord.Embed(
        title=f"{jogador['nome']} · Titular",
        description=f"Escalado com sucesso!\n\n{estrelas_overall(jogador['overall'])} · {medalha_overall(jogador['overall'])}",
        color=cor_por_overall(jogador["overall"])
    )
    embed.add_field(name="Posição", value=pos_full, inline=True)
    embed.add_field(name="Overall", value=f"{jogador['overall']}", inline=True)
    embed.add_field(name="Titulares", value=f"{len(titulares)}/11", inline=True)
    
    if jogador.get("imagem"):
        embed.set_thumbnail(url=jogador["imagem"])
    
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    embed.set_footer(text="TCSF Guru · Liga")
    await interaction.response.send_message(embed=embed)

@tree.command(name="elenco", description="Mostra o elenco titular (11 jogadores)")
@app_commands.describe(membro="Ver elenco de outro membro (opcional)")
async def elenco(interaction: discord.Interaction, membro: discord.Member = None):
    dados = carregar_dados()
    alvo = membro or interaction.user
    user_id = str(alvo.id)
    membro_dados = get_membro(dados, user_id)
    
    titulares = membro_dados.get("titulares", [])
    time_nome = membro_dados.get("time_nome") or f"Time de {alvo.display_name}"
    time_sigla = membro_dados.get("time_sigla") or "???"
    
    if not titulares:
        embed = discord.Embed(
            title="Sem titulares",
            description=f"{'Você não tem' if not membro else f'{alvo.display_name} não tem'} titulares definidos.",
            color=0x95a5a6
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    media = round(sum(j["overall"] for j in titulares) / len(titulares), 1)
    
    embed = discord.Embed(
        title=f"{time_nome} · {time_sigla}",
        description=f"{len(titulares)}/11 titulares · OVR médio: {media}\n{estrelas_overall(int(media))}",
        color=cor_por_overall(int(media))
    )
    
    posicoes_ordem = ["GOL", "ZAG", "LD", "LE", "VOL", "MEI", "ATA"]
    grupos = {}
    for j in titulares:
        grupos.setdefault(j["posicao"], []).append(j)
    
    for pos in posicoes_ordem:
        if pos in grupos:
            pos_full = POSICAO_FULL.get(pos, pos)
            linhas = []
            for j in grupos[pos]:
                linhas.append(f"{j['overall']} {estrelas_overall(j['overall'])} {j['nome']} — {j['clube']}")
            embed.add_field(name=pos_full, value="\n".join(linhas), inline=False)
    
    embed.set_author(name=alvo.display_name, icon_url=alvo.display_avatar.url)
    embed.set_footer(text=f"TCSF Guru · Liga · {datetime.now().strftime('%d/%m/%Y')}")
    await interaction.response.send_message(embed=embed)

@tree.command(name="carta", description="Mostra a carta de um jogador do seu elenco")
@app_commands.describe(nome="Nome do jogador")
async def carta(interaction: discord.Interaction, nome: str):
    dados = carregar_dados()
    user_id = str(interaction.user.id)
    membro_dados = get_membro(dados, user_id)
    
    todos = membro_dados.get("elenco", []) + membro_dados.get("titulares", [])
    vistos = set()
    jogadores_unicos = []
    for j in todos:
        if j["nome"] not in vistos:
            vistos.add(j["nome"])
            jogadores_unicos.append(j)
    
    jogador = next((j for j in jogadores_unicos if j["nome"].lower() == nome.lower()), None)
    if not jogador:
        embed = discord.Embed(
            title="Jogador não encontrado",
            description=f"{nome} não está no seu elenco.",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    pos_full = POSICAO_FULL.get(jogador["posicao"], jogador["posicao"])
    eh_titular = any(j["nome"].lower() == nome.lower() for j in membro_dados.get("titulares", []))
    
    embed = discord.Embed(
        title=jogador["nome"],
        description=(
            f"{medalha_overall(jogador['overall'])} · {estrelas_overall(jogador['overall'])}\n"
            f"{'[ TITULAR ]' if eh_titular else 'Reserva'}"
        ),
        color=cor_por_overall(jogador["overall"])
    )
    embed.add_field(name="Posição", value=pos_full, inline=True)
    embed.add_field(name="Overall", value=f"{jogador['overall']}", inline=True)
    embed.add_field(name="Clube", value=jogador["clube"], inline=True)
    embed.add_field(name="Valor de Mercado", value=fmt_reais(jogador["preco"]), inline=True)
    
    if jogador.get("imagem"):
        embed.set_image(url=jogador["imagem"])
    
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    embed.set_footer(text="TCSF Guru · Liga")
    await interaction.response.send_message(embed=embed)

@tree.command(name="saldo", description="Veja seu saldo na liga")
@app_commands.describe(membro="Ver saldo de outro membro (opcional)")
async def saldo(interaction: discord.Interaction, membro: discord.Member = None):
    dados = carregar_dados()
    alvo = membro or interaction.user
    user_id = str(alvo.id)
    membro_dados = get_membro(dados, user_id)
    salvar_dados(dados)
    
    coins = membro_dados["saldo"]
    
    if coins >= 10_000_000:
        nivel = "Magnata"
        cor = 0xffd700
    elif coins >= 1_000_000:
        nivel = "Rico"
        cor = 0x2ecc71
    elif coins >= 100_000:
        nivel = "Estável"
        cor = 0x1e90ff
    else:
        nivel = "Iniciante"
        cor = 0x95a5a6
    
    embed = discord.Embed(
        title="Carteira do Clube",
        description=f"Nível financeiro: {nivel}",
        color=cor
    )
    embed.set_author(name=alvo.display_name, icon_url=alvo.display_avatar.url)
    embed.add_field(name="Saldo Disponível", value=f"{fmt_reais(coins)}", inline=False)
    embed.set_footer(text=f"TCSF Guru · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    await interaction.response.send_message(embed=embed)

@tree.command(name="time", description="Veja ou defina o nome e sigla do seu time")
@app_commands.describe(
    nome="Nome do seu time (opcional)",
    sigla="Sigla do time (opcional)"
)
async def time(interaction: discord.Interaction, nome: str = None, sigla: str = None):
    dados = carregar_dados()
    user_id = str(interaction.user.id)
    membro_dados = get_membro(dados, user_id)
    
    if nome or sigla:
        if nome:
            membro_dados["time_nome"] = nome
        if sigla:
            membro_dados["time_sigla"] = sigla.upper()
        salvar_dados(dados)
        
        embed = discord.Embed(
            title="Clube Atualizado",
            description=f"As informações do seu clube foram salvas.",
            color=0x2ecc71
        )
        embed.add_field(name="Nome", value=membro_dados["time_nome"] or "Não definido", inline=True)
        embed.add_field(name="Sigla", value=membro_dados["time_sigla"] or "Não definida", inline=True)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text="TCSF Guru · Liga")
        await interaction.response.send_message(embed=embed)
        return
    
    time_nome = membro_dados.get("time_nome") or "Clube sem nome"
    time_sigla = membro_dados.get("time_sigla") or "???"
    elenco_lista = membro_dados.get("elenco", [])
    titulares_lista = membro_dados.get("titulares", [])
    media = round(sum(j["overall"] for j in titulares_lista) / len(titulares_lista), 1) if titulares_lista else 0
    
    embed = discord.Embed(
        title=f"{time_nome} [{time_sigla}]",
        description=(
            f"Overall médio: {media if media else '—'} · "
            f"Titulares: {len(titulares_lista)}/11\n"
            f"Saldo: {fmt_reais(membro_dados['saldo'])}"
        ),
        color=cor_por_overall(int(media)) if media else 0x95a5a6
    )
    
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    
    if elenco_lista:
        ordenados = sorted(elenco_lista, key=lambda j: j["overall"], reverse=True)
        linhas = [
            f"{j['overall']} {j['nome']} ({j['posicao']}) — {j['clube']}"
            for j in ordenados
        ]
        embed.add_field(
            name=f"Elenco Completo ({len(elenco_lista)} jogadores)",
            value="\n".join(linhas)[:1024],
            inline=False
        )
    else:
        embed.add_field(name="Elenco", value="Nenhum jogador. Use /obter!", inline=False)
    
    embed.set_footer(text=f"TCSF Guru · Liga · {datetime.now().strftime('%d/%m/%Y')}")
    await interaction.response.send_message(embed=embed)

@tree.command(name="listaplayers", description="[ADM] Lista todos os jogadores do banco")
async def listaplayers(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("Apenas administradores podem usar este comando.", ephemeral=True)
        return
    
    dados = carregar_dados()
    disponiveis = dados.get("jogadores_disponiveis", [])
    if not disponiveis:
        embed = discord.Embed(title="Banco Vazio", description="Nenhum jogador cadastrado.", color=0x95a5a6)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    ordenados = sorted(disponiveis, key=lambda j: j["overall"], reverse=True)
    
    embed = discord.Embed(
        title=f"Banco de Jogadores",
        description=f"{len(disponiveis)} jogadores disponíveis.",
        color=0x1e90ff
    )
    
    linhas = []
    for j in ordenados:
        img_tag = " 🖼" if j.get("imagem") else ""
        raridade = calcular_raridade(j)
        linhas.append(
            f"{j['overall']} {j['nome']} · {j['posicao']} · {j['clube']} · {fmt_reais(j['preco'])} · {raridade}{img_tag}"
        )
    
    embed.add_field(name="Jogadores", value="\n".join(linhas)[:4000], inline=False)
    embed.set_footer(text=f"TCSF Guru · ADM · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="setar", description="[ADM] Adiciona um jogador ao elenco de um membro")
@app_commands.describe(nome="Nome do jogador")
async def setar(interaction: discord.Interaction, nome: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Apenas administradores.", ephemeral=True)
        return
    
    dados = carregar_dados()
    disponiveis = dados.get("jogadores_disponiveis", [])
    
    if not disponiveis:
        embed = discord.Embed(
            title="❌ Banco Vazio",
            description="Não há jogadores no banco.",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    jogador = None
    for j in disponiveis:
        if nome.lower() in j["nome"].lower() or j["nome"].lower() in nome.lower():
            jogador = j
            break
    
    if not jogador:
        sugestoes = [j["nome"] for j in disponiveis if nome.lower()[0] == j["nome"].lower()[0]][:5]
        sugestoes_texto = "\n".join(f"• {s}" for s in sugestoes) if sugestoes else "Nenhuma sugestão."
        
        embed = discord.Embed(
            title="❌ Jogador Não Encontrado",
            description=f"**{nome}** não está no banco.\n\n**Sugestões:**\n{sugestoes_texto}",
            color=0xe74c3c
        )
        embed.set_footer(text="Use /listaplayers")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    pos_full = POSICAO_FULL.get(jogador["posicao"], jogador["posicao"])
    raridade = calcular_raridade(jogador)
    
    embed = discord.Embed(
        title=f"⚙️ Setar Jogador: {jogador['nome']}",
        description=f"{medalha_overall(jogador['overall'])} · {estrelas_overall(jogador['overall'])}\n\nSelecione o membro:",
        color=cor_por_overall(jogador["overall"])
    )
    embed.add_field(name="Posição", value=pos_full, inline=True)
    embed.add_field(name="Overall", value=f"{jogador['overall']}", inline=True)
    embed.add_field(name="Clube", value=jogador['clube'], inline=True)
    embed.add_field(name="Valor", value=fmt_reais(jogador['preco']), inline=True)
    embed.add_field(name="Raridade", value=raridade, inline=True)
    
    if jogador.get("imagem"):
        embed.set_thumbnail(url=jogador["imagem"])
    
    embed.set_footer(text=f"TCSF Guru · ADM · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    view = SelectMembroView(admin_id=interaction.user.id, jogador=jogador)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@tree.command(name="limpar_duplicatas", description="[ADM] Remove jogadores duplicados dos elencos")
async def limpar_duplicatas(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Apenas administradores.", ephemeral=True)
        return
    
    dados = carregar_dados(forcar_reload=True)
    
    total_removidos = 0
    for user_id, membro in dados["membros"].items():
        antes_elenco = len(membro.get("elenco", []))
        antes_titulares = len(membro.get("titulares", []))
        
        membro["elenco"] = remover_duplicatas_elenco(membro.get("elenco", []))
        membro["titulares"] = remover_duplicatas_elenco(membro.get("titulares", []))
        
        removidos = (antes_elenco - len(membro["elenco"])) + (antes_titulares - len(membro["titulares"]))
        total_removidos += removidos
    
    salvar_dados(dados)
    criar_backup()
    
    embed = discord.Embed(
        title="✅ Limpeza Concluída",
        description=f"**{total_removidos}** jogadores duplicados foram removidos.\n\nBackup criado automaticamente.",
        color=0x2ecc71
    )
    embed.set_footer(text=f"TCSF Guru · ADM · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ───────────────────────────────────────────
# INICIAR BOT
# ───────────────────────────────────────────
bot.run(TOKEN)