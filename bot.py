import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
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
BANNER_LIGA = None

# Dicionário para armazenar cooldowns (user_id: timestamp)
cooldowns_obter = {}

# ───────────────────────────────────────────
# SISTEMA DE CHANCE
# ───────────────────────────────────────────
def calcular_chance(jogador: dict) -> float:
    """
    Calcula a chance de obter um jogador baseado no overall e preço.
    Retorna um peso (quanto maior, mais raro).
    """
    overall = jogador.get("overall", 50)
    preco = jogador.get("preco", 1000)

    # Fator de raridade por overall
    if overall >= 95:
        fator_overall = 0.5  # 50% de chance base
    elif overall >= 90:
        fator_overall = 1.0  # 100%
    elif overall >= 85:
        fator_overall = 2.0  # 200%
    elif overall >= 80:
        fator_overall = 4.0  # 400%
    elif overall >= 70:
        fator_overall = 8.0  # 800%
    else:
        fator_overall = 15.0  # 1500% (muito comum)

    # Fator de raridade por preço
    if preco >= 10_000_000:
        fator_preco = 0.3
    elif preco >= 5_000_000:
        fator_preco = 0.6
    elif preco >= 1_000_000:
        fator_preco = 1.5
    elif preco >= 500_000:
        fator_preco = 3.0
    else:
        fator_preco = 6.0

    # Peso final (média dos fatores)
    peso = (fator_overall + fator_preco) / 2
    return peso

def sortear_jogador_ponderado(jogadores: list) -> dict:
    """
    Sorteia um jogador usando sistema de pesos (raridade).
    """
    if not jogadores:
        return None

    # Cria lista de pesos
    pesos = [calcular_chance(j) for j in jogadores]

    # Sorteia com base nos pesos
    jogador_sorteado = random.choices(jogadores, weights=pesos, k=1)[0]

    return jogador_sorteado

def calcular_raridade(jogador: dict) -> str:
    """
    Retorna uma string com a porcentagem de chance de obter o jogador.
    """
    peso = calcular_chance(jogador)

    # Calcula a raridade aproximada
    if peso >= 10:
        return "🟢 COMUM (Alta chance)"
    elif peso >= 5:
        return "🔵 INCOMUM (Boa chance)"
    elif peso >= 2:
        return "🟣 RARO (Chance média)"
    elif peso >= 1:
        return "🟠 ÉPICO (Baixa chance)"
    else:
        return "🔴 LENDÁRIO (Chance mínima)"

# ───────────────────────────────────────────
# UTILITÁRIOS DE DADOS
# ───────────────────────────────────────────
def carregar_dados():
    if not os.path.exists(DATA_FILE):
        return {"jogadores_disponiveis": [], "membros": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def salvar_dados(dados):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

def get_membro(dados, user_id: str):
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
    return any(r.id in ADMIN_ROLE_IDS for r in interaction.user.roles)

def fmt_reais(valor) -> str:
    return f"R$ {int(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def cor_por_overall(overall: int) -> int:
    if overall >= 99:
        return 0xff4500
    if overall >= 90:
        return 0xffd700
    if overall >= 85:
        return 0xb44fea
    if overall >= 80:
        return 0x1e90ff
    if overall >= 70:
        return 0x2ecc71
    return 0x95a5a6

def medalha_overall(overall: int) -> str:
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
    if overall >= 90:
        return "★★★★★"
    if overall >= 80:
        return "★★★★☆"
    if overall >= 70:
        return "★★★☆☆"
    if overall >= 60:
        return "★★☆☆☆"
    return "★☆☆☆☆"

POSICAO_FULL = {
    "GOL": "Goleiro",
    "ZAG": "Zagueiro",
    "LD": "Lateral Direito",
    "LE": "Lateral Esquerdo",
    "VOL": "Volante",
    "MEI": "Meia",
    "ATA": "Atacante"
}

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
        self.total_paginas = (len(self.jogadores) - 1) // self.itens_por_pagina + 1

        self.atualizar_botoes()

    def atualizar_botoes(self):
        self.clear_items()

        # Botões de navegação
        if self.pagina > 0:
            self.add_item(BotaoAnterior())

        if self.pagina < self.total_paginas - 1:
            self.add_item(BotaoProximo())

        # Botões de jogadores da página atual
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
            
            embed.add_field(
                name=f"{pode_comprar} {jogador['nome']} · {jogador['overall']} OVR",
                value=f"{pos_full} · {jogador['clube']}\n💰 {fmt_reais(jogador['preco'])}",
                inline=True
            )

        embed.set_footer(text=f"TCSF Guru · Página {self.pagina + 1}/{self.total_paginas} · {len(self.jogadores)} jogadores disponíveis")
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

        # Define cor do botão baseado no overall
        if jogador["overall"] >= 90:
            style = discord.ButtonStyle.success
        elif jogador["overall"] >= 80:
            style = discord.ButtonStyle.primary
        else:
            style = discord.ButtonStyle.secondary

        super().__init__(
            label=label,
            style=style,
            row=(posicao // 5) + 1  # Organiza em linhas
        )

    async def callback(self, interaction: discord.Interaction):
        dados = carregar_dados()
        user_id = str(interaction.user.id)
        membro = get_membro(dados, user_id)

        preco = self.jogador.get("preco", 0)
        saldo = membro.get("saldo", 0)

        # Verifica se tem saldo suficiente
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

        # Verifica se já tem o jogador
        if any(j["nome"].lower() == self.jogador["nome"].lower() for j in membro.get("elenco", [])):
            await interaction.response.send_message(
                f"Você já tem **{self.jogador['nome']}** no seu elenco!",
                ephemeral=True
            )
            return

        # Realiza a compra
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

        # Atualiza a view
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
# VIEW COM SELECT MENU PARA SETAR JOGADOR
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
        
        # Verifica se já tem o jogador
        if any(j["nome"].lower() == self.jogador["nome"].lower() for j in membro_dados.get("elenco", [])):
            await interaction.response.send_message(
                f"❌ **{membro_selecionado.display_name}** já possui **{self.jogador['nome']}** no elenco!",
                ephemeral=True
            )
            return
        
        # Adiciona o jogador ao elenco
        membro_dados["elenco"].append(self.jogador)
        salvar_dados(dados)
        
        pos_full = POSICAO_FULL.get(self.jogador["posicao"], self.jogador["posicao"])
        
        # Embed de confirmação
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
        
        # Desabilita o select após uso
        for child in self.children:
            child.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Notifica o membro (opcional)
        try:
            notif_embed = discord.Embed(
                title="🎁 Novo Jogador Recebido!",
                description=f"Você recebeu **{self.jogador['nome']}** ({self.jogador['overall']} OVR) no seu elenco!",
                color=cor_por_overall(self.jogador["overall"])
            )
            notif_embed.set_footer(text="TCSF Guru · Liga")
            await membro_selecionado.send(embed=notif_embed)
        except:
            pass  # Caso o membro tenha DM desabilitada

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
    await tree.sync()
    print(f"Bot online como {bot.user} | Liga: TCSF Guru")

# ───────────────────────────────────────────
# /addplayer (só ADM)
# ───────────────────────────────────────────
@tree.command(name="addplayer", description="[ADM] Adiciona um jogador ao banco com imagem da carta")
@app_commands.describe(
    nome="Nome do jogador",
    posicao="Posicao (GOL, ZAG, LD, LE, VOL, MEI, ATA)",
    overall="Overall do jogador (1-99)",
    clube="Clube do jogador",
    preco="Preco em reais",
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
    jogador = {
        "nome": nome,
        "posicao": posicao.upper(),
        "overall": overall,
        "clube": clube,
        "preco": preco,
        "imagem": imagem or None
    }
    dados["jogadores_disponiveis"].append(jogador)
    salvar_dados(dados)

    pos_full = POSICAO_FULL.get(posicao.upper(), posicao.upper())
    raridade = calcular_raridade(jogador)

    embed = discord.Embed(
        title=f"{nome}",
        description=f"{medalha_overall(overall)} · {estrelas_overall(overall)}\n\nJogador adicionado ao banco da liga.",
        color=cor_por_overall(overall)
    )
    embed.add_field(name="Posição", value=pos_full, inline=True)
    embed.add_field(name="Overall", value=f"{overall}", inline=True)
    embed.add_field(name="Clube", value=clube, inline=True)
    embed.add_field(name="Valor de Mercado", value=fmt_reais(preco), inline=True)
    embed.add_field(name="Raridade", value=raridade, inline=True)
    embed.add_field(name="Total no banco", value=f"{len(dados['jogadores_disponiveis'])} jogadores", inline=True)

    if imagem:
        embed.set_image(url=imagem)

    embed.set_footer(text=f"TCSF Guru · ADM · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    await interaction.response.send_message(embed=embed)

# ───────────────────────────────────────────
# /comprar (NOVO COMANDO)
# ───────────────────────────────────────────
@tree.command(name="comprar", description="Abre o mercado de transferências para comprar jogadores")
async def comprar(interaction: discord.Interaction):
    dados = carregar_dados()
    disponiveis = dados.get("jogadores_disponiveis", [])

    if not disponiveis:
        embed = discord.Embed(
            title="🏪 Mercado Vazio",
            description="Não há jogadores disponíveis para compra no momento.\nAguarde o administrador adicionar novos jogadores.",
            color=0x95a5a6
        )
        embed.set_footer(text="TCSF Guru · Liga")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    view = ListaJogadoresView(interaction.user.id, disponiveis)
    embed = view.get_embed()

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ───────────────────────────────────────────
# /obter (COM SISTEMA DE CHANCE E COOLDOWN)
# ───────────────────────────────────────────
@tree.command(name="obter", description="Sorteia um jogador do banco para o seu elenco")
async def obter(interaction: discord.Interaction):
    user_id = interaction.user.id

    # ✅ VERIFICAÇÃO DE COOLDOWN (exceto para admins)
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

        # Atualiza o cooldown
        cooldowns_obter[user_id] = agora

    dados = carregar_dados()
    disponiveis = dados.get("jogadores_disponiveis", [])

    if not disponiveis:
        embed = discord.Embed(
            title="Banco Vazio",
            description="Nenhum jogador disponível no momento.\nAguarde o administrador adicionar novos jogadores.",
            color=0x95a5a6
        )
        embed.set_footer(text="TCSF Guru · Liga")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    user_id_str = str(interaction.user.id)
    membro = get_membro(dados, user_id_str)

    # ✨ SORTEIA COM BASE NA RARIDADE
    jogador = sortear_jogador_ponderado(disponiveis)
    raridade = calcular_raridade(jogador)

    membro["elenco"].append(jogador)
    salvar_dados(dados)

    pos_full = POSICAO_FULL.get(jogador["posicao"], jogador["posicao"])
    cor = cor_por_overall(jogador["overall"])

    embed = discord.Embed(
        title=f"{jogador['nome']}",
        description=(
            f"{medalha_overall(jogador['overall'])} · {estrelas_overall(jogador['overall'])}\n\n"
            f"{interaction.user.display_name} recebeu um novo reforço!\n"
            f"Raridade: {raridade}\n\n"
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

# ───────────────────────────────────────────
# /promover
# ───────────────────────────────────────────
@tree.command(name="promover", description="Promove um jogador do seu elenco para titular")
@app_commands.describe(nome="Nome do jogador que deseja promover para titular")
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
            description=f"{nome} não está no seu elenco.\nUse /time para ver seus jogadores.",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if any(j["nome"].lower() == nome.lower() for j in titulares):
        await interaction.response.send_message(f"{nome} já está entre os titulares.", ephemeral=True)
        return

    if len(titulares) >= 11:
        await interaction.response.send_message("Você já tem 11 titulares. Remova um antes de promover outro.", ephemeral=True)
        return

    titulares.append(jogador)
    membro["titulares"] = titulares
    salvar_dados(dados)

    pos_full = POSICAO_FULL.get(jogador["posicao"], jogador["posicao"])

    embed = discord.Embed(
        title=f"{jogador['nome']} · Titular",
        description=f"Escalado com sucesso para o time titular!\n\n{estrelas_overall(jogador['overall'])} · {medalha_overall(jogador['overall'])}",
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

# ───────────────────────────────────────────
# /elenco
# ───────────────────────────────────────────
@tree.command(name="elenco", description="Mostra o elenco titular (11 jogadores)")
@app_commands.describe(membro="Veja o elenco de outro membro (opcional)")
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
            description=f"{'Você não tem' if not membro else f'{alvo.display_name} não tem'} titulares definidos.\nUse /promover para escalar jogadores.",
            color=0x95a5a6
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Calcula overall médio
    media = round(sum(j["overall"] for j in titulares) / len(titulares), 1)

    embed = discord.Embed(
        title=f"{time_nome} · {time_sigla}",
        description=f"{len(titulares)}/11 titulares escalados · Overall médio: {media}\n{estrelas_overall(int(media))}",
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

    for pos, jogadores in grupos.items():
        if pos not in posicoes_ordem:
            linhas = [f"{j['overall']} {j['nome']} — {j['clube']}" for j in jogadores]
            embed.add_field(name=pos, value="\n".join(linhas), inline=False)

    embed.set_author(name=alvo.display_name, icon_url=alvo.display_avatar.url)
    embed.set_footer(text=f"TCSF Guru · Liga · {datetime.now().strftime('%d/%m/%Y')}")
    await interaction.response.send_message(embed=embed)

# ───────────────────────────────────────────
# /carta
# ───────────────────────────────────────────
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

# ───────────────────────────────────────────
# /saldo
# ───────────────────────────────────────────
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

# ───────────────────────────────────────────
# /time
# ───────────────────────────────────────────
@tree.command(name="time", description="Veja ou defina o nome e sigla do seu time")
@app_commands.describe(
    nome="Nome do seu time (opcional)",
    sigla="Sigla do time, ex: FLA (opcional)"
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
            description=f"As informações do seu clube foram salvas com sucesso.",
            color=0x2ecc71
        )
        embed.add_field(name="Nome", value=membro_dados["time_nome"] or "Não definido", inline=True)
        embed.add_field(name="Sigla", value=membro_dados["time_sigla"] or "Não definida", inline=True)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text="TCSF Guru · Liga")
        await interaction.response.send_message(embed=embed)
        return

    # Visualizar
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
        # Ordena por overall decrescente
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
        embed.add_field(name="Elenco", value="Nenhum jogador ainda. Use /obter!", inline=False)

    embed.set_footer(text=f"TCSF Guru · Liga · {datetime.now().strftime('%d/%m/%Y')}")
    await interaction.response.send_message(embed=embed)

# ───────────────────────────────────────────
# /listaplayers (só ADM)
# ───────────────────────────────────────────
@tree.command(name="listaplayers", description="[ADM] Lista todos os jogadores disponíveis no banco")
async def listaplayers(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("Apenas administradores podem usar este comando.", ephemeral=True)
        return

    dados = carregar_dados()
    disponiveis = dados.get("jogadores_disponiveis", [])
    if not disponiveis:
        embed = discord.Embed(title="Banco Vazio", description="Nenhum jogador cadastrado ainda.", color=0x95a5a6)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Ordena por overall decrescente
    ordenados = sorted(disponiveis, key=lambda j: j["overall"], reverse=True)

    embed = discord.Embed(
        title=f"Banco de Jogadores",
        description=f"{len(disponiveis)} jogadores disponíveis no banco da liga.",
        color=0x1e90ff
    )

    linhas = []
    for j in ordenados:
        img_tag = " 🖼" if j.get("imagem") else ""
        linhas.append(
            f"{j['overall']} {j['nome']} · {j['posicao']} · {j['clube']} · {fmt_reais(j['preco'])}{img_tag}"
        )

    embed.add_field(name="Jogadores", value="\n".join(linhas)[:4000], inline=False)
    embed.set_footer(text=f"TCSF Guru · ADM · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ───────────────────────────────────────────
# /setar (só ADM)
# ───────────────────────────────────────────
@tree.command(name="setar", description="[ADM] Adiciona um jogador do banco ao elenco de um membro")
@app_commands.describe(nome="Nome do jogador que deseja setar")
async def setar(interaction: discord.Interaction, nome: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Apenas administradores podem usar este comando.", ephemeral=True)
        return
    
    dados = carregar_dados()
    disponiveis = dados.get("jogadores_disponiveis", [])
    
    if not disponiveis:
        embed = discord.Embed(
            title="❌ Banco Vazio",
            description="Não há jogadores disponíveis no banco.\nUse `/addplayer` para adicionar jogadores.",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Procura o jogador (busca flexível)
    jogador = None
    for j in disponiveis:
        if nome.lower() in j["nome"].lower() or j["nome"].lower() in nome.lower():
            jogador = j
            break
    
    if not jogador:
        # Lista sugestões se não encontrar
        sugestoes = [j["nome"] for j in disponiveis if nome.lower()[0] == j["nome"].lower()[0]][:5]
        sugestoes_texto = "\n".join(f"• {s}" for s in sugestoes) if sugestoes else "Nenhuma sugestão disponível."
        
        embed = discord.Embed(
            title="❌ Jogador Não Encontrado",
            description=f"O jogador **{nome}** não está no banco de jogadores.\n\n**Sugestões:**\n{sugestoes_texto}",
            color=0xe74c3c
        )
        embed.set_footer(text="Use /listaplayers para ver todos os jogadores")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Mostra informações do jogador e select menu
    pos_full = POSICAO_FULL.get(jogador["posicao"], jogador["posicao"])
    raridade = calcular_raridade(jogador)
    
    embed = discord.Embed(
        title=f"⚙️ Setar Jogador: {jogador['nome']}",
        description=f"{medalha_overall(jogador['overall'])} · {estrelas_overall(jogador['overall'])}\n\nSelecione o membro que receberá este jogador:",
        color=cor_por_overall(jogador["overall"])
    )
    embed.add_field(name="Posição", value=pos_full, inline=True)
    embed.add_field(name="Overall", value=f"{jogador['overall']}", inline=True)
    embed.add_field(name="Clube", value=jogador['clube'], inline=True)
    embed.add_field(name="Valor de Mercado", value=fmt_reais(jogador['preco']), inline=True)
    embed.add_field(name="Raridade", value=raridade, inline=True)
    
    if jogador.get("imagem"):
        embed.set_thumbnail(url=jogador["imagem"])
    
    embed.set_footer(text=f"TCSF Guru · ADM · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    view = SelectMembroView(admin_id=interaction.user.id, jogador=jogador)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ───────────────────────────────────────────
# INICIAR
# ───────────────────────────────────────────
bot.run(TOKEN)