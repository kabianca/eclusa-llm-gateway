# Eclusa

### Uma pergunta entra. O que sai foi conferido, cobrado e registrado.

Um gateway de LLM sobre os atos normativos do Banco Central do Brasil em matéria
de prevenção à lavagem de dinheiro e ao financiamento do terrorismo (PLD/FT). Uma
pergunta entra, a resposta é conferida contra um contrato — toda afirmação
rastreável a uma passagem recuperada, ou a resposta é recusada —, o orçamento é
debitado, o registro de auditoria é escrito, e só então a resposta sai.

<p>
  <a href="https://github.com/kabianca/eclusa-llm-gateway/actions/workflows/tests.yml">
    <img src="https://github.com/kabianca/eclusa-llm-gateway/actions/workflows/tests.yml/badge.svg" alt="tests">
  </a>
  <a href="https://github.com/kabianca/eclusa-llm-gateway/actions/workflows/kind.yml">
    <img src="https://github.com/kabianca/eclusa-llm-gateway/actions/workflows/kind.yml/badge.svg" alt="kind">
  </a>
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/license-GPL--3.0-green" alt="GPL-3.0 license">
</p>

[English](README.md) · **Português**

A tese: **um LLM em produção é um orçamento, um contrato e uma trilha de
auditoria. O modelo é a parte fácil.** Este repositório não afirma que previne
alucinação; essa afirmação não é testável. Ele afirma algo mais estreito e
demonstrável: uma resposta sem citação que resolva para o corpus congelado é uma
recusa, e o corpus e o modelo estão fixados para que uma avaliação meça o
pipeline, e não o que se moveu por baixo dele.

Este é o quinto repositório de uma série — [Maré](https://github.com/kabianca/bcb-airflow-pipeline),
[Âncora](https://github.com/kabianca/cohort-rfm-ecommerce),
[Estrato](https://github.com/kabianca/estrato-claims-warehouse),
[Foz](https://github.com/kabianca/foz-payments-stream) — e todos defendem uma
mesma disciplina: fixe o que se move, ou sua medição não mede nada. Âncora fixa a
recência a uma data de corte, Estrato reexecuta por `as_of`, Foz fecha a janela
com um watermark. A Eclusa fixa o corpus e o modelo. Maré lê o que o banco
central *mede* (a API de séries numéricas do SGS); a Eclusa lê o que ele
*determina* (atos normativos, que não estão no portal de dados abertos — serviço
diferente, alcançado de outro jeito).

## Por que eu construí isto

Toda demonstração de geração aumentada por recuperação que eu tinha lido media o
modelo. Nenhuma media as coisas que decidem se a resposta pode ser confiada: se a
citação resolve, se o corpus se moveu por baixo da avaliação, quanto custou a
chamada, e o que ficou registrado quando a resposta foi recusada. São essas as
partes sobre as quais um auditor pergunta, e são as partes que faltam.

Por isso o assunto é um que eu consigo julgar — as regras de PLD/FT do Banco
Central — e o corpus é congelado, porque um corpus que muda por baixo do sistema
torna a avaliação sem sentido: uma regressão pode ser o prompt, ou pode ser uma
norma revogada, e não há como saber. O mesmo ato é guardado em duas versões, de
propósito. Perguntado quando a Circular 3.978 entra em vigor, um sistema que não
modela versão responde *1º de julho de 2020* com total confiança — uma data que
nunca entrou em vigor, porque a Circular 4.005 a mudou para outubro. Esse erro
não é hipotético: é o que um analista de compliance faz toda semana quando uma
busca o deixa no PDF original.

## Arquitetura

```
corpus/      21 atos normativos, congelados: a captura, o texto extraído e, para
             cada um, a URL de origem, a data de captura, o hash e a versão do
             extrator que o produziu
collector/   o caminho opcional de atualização: educado, verificado por hash,
             reporta deriva em vez de sobrescrever. Nunca necessário para rodar
ingest/      duas rotas de extração reduzidas a uma forma, e segmentação que dá
             a cada parágrafo um localizador: art. 24, § 3º, VI, g, 2
index/       chunking em unidades, avisos e alterações; modelo de embedding
             multilíngue local, fixado por revisão e hash de arquivo; busca exata
service/     a eclusa: contrato -> orçamento -> provedor -> auditoria, sob HTTP
eval/        recuperação e geração medidas em separado, ambas congeladas antes
k8s/         os manifests e a configuração do kind a que o CI os aplica
```

O ciclo, para uma pergunta:

```
pergunta
  -> recuperação   ciente de versão: texto em vigor primeiro, histórico só onde
                   difere, o aviso de revogação anexado por regra
  -> orçamento     o teto compra um número de tokens de saída; se o que sobra
                   compra poucos demais, a chamada não é feita
  -> provedor      gravações por padrão; o modelo vivo só com uma flag e uma
                   chave, as duas postas deliberadamente
  -> contrato      toda afirmação cita uma passagem recuperada para *esta*
                   requisição, num localizador que existe dentro dela; texto
                   superado exige a versão em vigor, texto revogado exige a sua
                   revogação
  -> auditoria     um registro, acrescentado, incluindo os rascunhos bloqueados
                   e o que eles tentaram dizer
resposta, ou uma recusa que diz por quê
```

## O que apareceu rodando

**Um artigo inserido mudou o dono de um título, e teria deslocado a comparação
entre versões.** O corpus guarda a Circular 3.978 duas vezes: a redação original
(v1, do HTML do endpoint) e a consolidação atual (v5, de PDF). Um teste compara
as duas artigo a artigo e espera que os artigos que nenhuma alteração tocou saiam
byte a byte idênticos pelas duas rotas. O art. 23 falhou, e o texto dele não
havia mudado. A Resolução BCB 344/2023 inseriu o art. 23-A logo depois dele, no
fim da seção, e o título de seção seguinte (*Da Identificação e da Qualificação
do Beneficiário Final*) estava sendo atribuído ao artigo anterior, qualquer que
fosse: art. 23 no v1, art. 23-A no v5. O extrator dava títulos ao artigo de cima.
Um título com dono errado é coisa pequena até cair na comparação entre versões,
que é o caso que este projeto põe na vitrine: teria reportado diferença num
artigo que não mudou. Títulos de seção agora são cabeçalhos por direito próprio e
não pertencem a artigo nenhum. Um teste pegou isso antes de existir uma linha de
código de LLM.

**Quatro leiautes de rodapé, e o documento de uma página que não tem nenhum.**
Cada página dos PDFs do BCB fecha com um rodapé corrente, e a primeira versão do
extrator o encontrava por repetição: a linha que fecha a maioria das páginas.
Passou nos três documentos de amostra. No corpus inteiro, encontrou um ato de
2010 cujo rodapé é só o título (*Circular nº 3517, 7 de dezembro de 2010*, sem
número de página), um de 2012 cujo rodapé aparece só na página dois, um de 2009
com número de página solto, e atos de uma página sem rodapé algum — para os quais
"a maioria das páginas" não significa nada. Deixado ali, um rodapé gruda no fim
do parágrafo que a quebra de página interrompeu, e uma citação a esse parágrafo
cita o rodapé como se fosse lei. A regra agora é posicional e específica do
documento: a última linha de uma página é rodapé se começa com a designação do
próprio ato, que o manifesto conhece. Coletar o corpus inteiro *antes* de
escrever o segmentador foi o que tornou isso visível; um segmentador validado em
três amostras teria entregado a regra da repetição.

**Sessenta e dois de setenta artigos idênticos pelas duas rotas de extração, e os
outros oito, um a um.** A comparação entre versões só significa algo se o que
difere entre v1 e v5 for regulação, e não extração. Então os oito artigos
divergentes foram classificados individualmente, em vez de declarados "mudança
real": arts. 16, 18, 24 e 33 alterados pela Resolução BCB 119/2021; 28 e 68 pela
Resolução BCB 282/2022; 70 (a entrada em vigor, de *julho* para *outubro*) pela
Circular 4.005/2020; e 69, cujo inciso XVII ganhou uma remissão editorial (*Vide
Circular nº 3.942*) na consolidação. Toda alteração carrega sua proveniência
inline no texto consolidado; nenhuma é artefato da rota HTML contra PDF. A
pergunta "quando a Circular 3.978 entra em vigor?" tem portanto uma resposta
limpa para demonstrar: o texto consolidado diz 1º de outubro de 2020, redação
dada pela Circular 4.005; o original dizia 1º de julho. Um sistema que não modela
versão responde *julho* com total confiança. É esse o erro que o corpus foi
montado para pegar.

**A rota documentada existe e está fechada.** O plano era alcançar os textos
normativos pelo LexML, cuja API SRU é documentada, antes de tocar no endpoint não
documentado por trás da página *Busca de Normas* do BCB. O LexML foi tentado
primeiro. Toda requisição — inclusive `operation=explain`, com User-Agent de
navegador — é respondida com uma página de segurança do Senado Federal: um
desafio de prova de trabalho em JavaScript (SHA-256 sobre
`ip;hostname;timestamp;nonce`, dificuldade 3, enviado a `/_challenge`). Resolvê-lo
programaticamente seria burlar um controle antiautomação no site de uma
instituição pública, e código de contorno num repositório público é péssima coisa
de se mostrar a quem avalia. Então o coletor usa o endpoint do BCB, e o README
diz isso: `exibenormativo` devolve os metadados do ato, sua redação *original* em
HTML e uma lista de anexos em PDF; versões consolidadas existem apenas como esses
PDFs (`_L`, limpo; `_P`, marcado — que duplica todo artigo alterado e nunca é
ingerido). Dois atos têm o texto HTML vazio no endpoint e são capturados do PDF.
Toda requisição do coletor nomeia este projeto no User-Agent e espera dois
segundos; vinte e um documentos tornam o volume irrelevante, mas o código é
público e um coletor sem intervalo é mau exemplo.

**Um hash que teria derivado sem o texto mudar.** O coletor registra o SHA-256 de
cada documento capturado para que uma atualização futura detecte deriva em vez de
sobrescrever o snapshot em silêncio. A primeira versão fazia o hash da resposta
JSON inteira do endpoint, na rota HTML. Essa resposta carrega `NormasVinculadas`
— a lista de atos que citam este —, que cresce toda vez que o BCB publica um novo
ato referindo-se à Circular 3.978, tenha ou não mudado uma palavra da circular. O
hash teria gritado deriva a cada citação. O que se captura agora é só o campo
`Texto`, a redação que o sistema consome, e o hash cobre isso. Mudança real e
mudança aparente são coisas diferentes, e distingui-las é o que o projeto inteiro
argumenta; este foi o menor lugar onde isso apareceu.

**A página do próprio ato traz um memorando que não é o ato.** Nas Instruções
Normativas, o texto do endpoint não termina na assinatura. Depois dela vem a
*NOTA 388/2026-BCB/DENOR* — a nota técnica que propôs o ato, com seus
destinatários, seus parágrafos numerados de 1 a 8 e um segundo bloco de
assinaturas. Um percurso que atribui tudo o que vem depois do último artigo a
esse artigo lia aqueles parágrafos como itens 1 a 8 do art. 3º. A moldura de um
documento agora é encontrada a partir do seu início — o primeiro parágrafo depois
do último artigo que pareça assinatura, data ou nota do DOU a abre, e tudo o que
vem depois pertence a ela — e a nota é guardada como anexo: pública, útil para
"por que isto mudou?", nunca citável como norma.

**"Verificado à mão" tem que significar verificado à mão.** O teste que fixa a
forma da Carta Circular 4.001 afirmava 161 alíneas sob o art. 1º, e eu escrevi no
comentário que o número fora conferido à mão. Não fora. Veio de uma expressão
regular que casava `a)` até `z)` e parava; o ato continua com `aa)` até `ae)`. Eu
tinha verificado o código com a saída do próprio código e chamado aquilo de
conferência. Quando as alíneas de duas letras apareceram, afirmei que estavam sob
o inciso XVI — de memória, sem olhar — e o teste falhou de novo: estão sob o
inciso IV. Duas afirmações não verificadas, ambas pegas por testes escritos para
fixar fatos conferidos à mão, nenhum dos quais havia sido. O teste agora diz 166
e IV, e o comentário acima dele diz como o primeiro número estava errado. Uma
contagem produzida pelo código sob teste não é uma conferência do código sob
teste, e uma afirmação feita sem abrir o documento não é um fato — é exatamente o
tipo de resposta confiante e errada que este projeto existe para recusar.

**O extrator é parte do pipeline, então a versão dele é fixada e registrada.** O
texto commitado precisa ser igual ao que os arquivos brutos extraem, byte a byte
— é isso que torna o texto do corpus auditável. O runner Ubuntu do GitHub traz
poppler 24.02; a máquina onde o corpus foi extraído traz 25.03. Mesmo PDF, dois
majors de poppler, nenhuma garantia da mesma saída. A primeira correção foi rodar
o job de teste dentro de uma imagem Debian que por acaso carrega 25.03 — o que
faz o teste passar deixando a dependência implícita: nada no repositório dizia de
qual poppler o texto precisava, e a tag da imagem se move. Então o manifesto agora
registra `extractor_version` ao lado de cada hash de texto, o workflow instala
`poppler-utils=25.03.0-*` explicitamente, e um teste compara a versão instalada
com a registrada *antes* de comparar bytes — de modo que a divergência é relatada
como "corpus/text foi extraído com pdftotext 25.03.0; este ambiente tem 24.02.0",
e não como um diff inexplicado. É a mesma disciplina do corpus congelado e do
identificador datado do modelo, uma camada abaixo: fixe o que se move, e registre
o que você fixou.

**Uma fronteira neste README não era uma fronteira; era uma decisão minha.** Este
arquivo afirmava, como propriedade do corpus, que ele responde o que está em
vigor e não o histórico de alterações: que *"O que a Resolução BCB 344 mudou?"*
não tinha resposta, que o corpus contém o ato e não o seu diff. Foi escrito com
convicção e estava errado. O art. 1º da Resolução 344 é seguido, no corpus, pelo
texto integral que ela deu ao art. 23-A, fechando com *(NR)* — o ato enuncia o
próprio efeito de forma exaustiva. O que não tinha resposta era o **índice**,
porque o chunker descartava todo bloco que um ato alterador transcreve — dez por
cento do corpus, 183 de 1.873 parágrafos — sob o argumento razoável de que
duplicam texto consolidado e competiriam com ele na recuperação. A competição é
real; descartar um décimo do corpus não era a única forma de evitá-la. Foi preciso
uma leitora dizer "olhe as oito linhas depois da passagem que você citou" para
enxergar. Esses blocos agora são indexados, como um tipo próprio de chunk,
rebaixados abaixo do texto em vigor a menos que a pergunta nomeie o ato alterador
— a regra que o aviso de revogação já usava. No conjunto congelado, a métrica nova
foi de 0 a 100%, nada regrediu, e a média do inverso da posição dos dispositivos
em vigor subiu de 0,80 para 0,85, porque um caso — a Circular 3.978 altera a
circular de câmbio? — vinha sendo ranqueado por um caput cujo conteúdo estava
sendo jogado fora. A lição não é sobre chunking. Uma limitação que vale pôr num
README vale ser conferida contra o corpus antes, ou você publica a sua própria
escolha de implementação como um fato sobre o mundo.

**A armadilha da versão tem um número.** A primeira pergunta feita ao índice
pronto foi o caso de demonstração, *"Quando a Circular 3.978 entra em vigor?"* O
primeiro colocado foi o art. 70 do texto **original** — *1º de julho de 2020*,
data que nunca entrou em vigor — com 0,9145. O art. 70 consolidado, o que é lei,
veio em quarto com 0,9028, porque carrega o marcador *(Redação dada, a partir de
1º/6/2020, pela Circular nº 4.005)* e as palavras a mais diluem a similaridade. É
esta a falha que o corpus foi montado para expor: dois textos quase idênticos do
mesmo ato, e a similaridade de embedding preferindo o superado por ser mais curto.
Nenhum flag no documento resolve isso; a recuperação precisa saber o que é uma
versão.

O par de números, então — porque um número sozinho se lê como problema não
resolvido. Antes de tocar na recuperação, vinte e quatro perguntas sensíveis a
versão e cinco métricas foram escritas e congeladas (`eval/retrieval/METRIC.md`),
para que a correção não pudesse ser ajustada ao próprio teste. Nesse conjunto, o
índice cru encontrou o dispositivo esperado em 92% dos casos, mas colocou a versão
em vigor em primeiro em **25%** — e em **0%** dos dispositivos cuja redação nunca
mudou, porque textos idênticos empatam e o desempate por id de chunk escolhia
`@v1` antes de `@v5`, por ordem alfabética. Um empate é uma decisão; aquela estava
errada. A camada ciente de versão não muda score nenhum: agrupa chunks por ato e
unidade, põe a versão em vigor primeiro, mantém a original só onde a redação
difere, ranqueia atos revogados abaixo dos atos em vigor a menos que a pergunta os
nomeie, e anexa o aviso de revogação por regra. No mesmo conjunto congelado:
vigente em primeiro **100%**, média do inverso da posição do dispositivo em vigor
de 0,38 para 0,80, revogado abaixo do vigente de 60% para 100%, aviso de revogação
presente de 0% para 100%. O dispositivo foi encontrado nos mesmos 92% — a camada
não encontra o que o embedding não acha, e não finge que encontra.

Três desses números foram a 100% porque a camada garante a propriedade por
construção — a versão em vigor vem do índice por regra, o aviso é anexado por
regra. Eles medem que a regra foi aplicada, não que a regra está certa: são
guardas de regressão, e são reportados como tal. O número que mede recuperação é o
que não se moveu. E uma regra só está testada onde ela dispara, a menos que o
conjunto também guarde os casos em que ela não deve: duas perguntas que nomeiam o
ato revogado, nas quais forçar o texto em vigor em primeiro seria errado, e duas
que perguntam pela redação original, nas quais descartá-la seria — acrescentadas
por aditamento documentado ao conjunto congelado, e passando antes e depois, que é
o que mostra que as regras têm uma exceção que funciona.

**Um quase-acerto quebrou o binário.** "Quais procedimentos devem ser adotados na
compra de ouro?" deveria ser uma recusa: o ato que regula a compra de ouro está
fora do corpus. Mas a Carta Circular 4.001 lista situações de indício
*relacionadas com o mercado de ouro* (inciso XIX, incluído em 2024), então a
recuperação devolve algo com cara de relevante. A resposta honesta não é nem
resposta nem recusa, e o contrato como desenhado a princípio — responder ou
recusar — não tinha lugar para ela. A maioria dos sistemas de RAG responde a parte
coberta e cala sobre o resto, que é a forma mais perigosa de estar errado, porque
parece completa. Então o contrato tem agora três desfechos: *respondido*,
*recusado* e *parcial* — o sistema responde o que o corpus cobre e declara, num
campo próprio, o que não cobre. O parcial tem valor próprio na trilha de auditoria
e testes próprios. A pergunta do ouro é a sua vitrine: *o corpus cobre situações
de indício ligadas ao mercado de ouro (Carta Circular 4.001, art. 1º, XIX); não
cobre procedimentos de compra, que estão na Instrução Normativa BCB 406/2023, fora
deste corpus.* Essa frase convence mais do que qualquer recusa.

**O que o modelo fez ao encontrar o contrato.** Os quinze casos de avaliação foram
gravados uma vez contra o modelo vivo, por quatro centavos e meio, e avaliados à
mão contra o texto do corpus — sem juiz-LLM, porque um projeto cuja tese é
determinismo não deveria parafusar um segundo componente não determinístico na
própria medição. Dez passaram. Cinco não, e nenhum falhou em silêncio. Três foram
barrados pelo contrato: perguntado o que a Circular 3.461 *exige* — presente do
indicativo, sobre um ato revogado em 2020 — o modelo respondeu que ela *exige*,
com a revogação parada, sem uso, no próprio contexto; perguntado o que a redação
original da Circular 3.978 previa, respondeu *1º de julho de 2020* e parou ali,
uma data que nunca entrou em vigor. Um pipeline de recuperação comum teria
entregado os três como respostas confiantes, citadas e erradas. Os outros dois
eram perguntas que os casos mandam recusar por ambiguidade, e que o modelo
respondeu por uma das leituras em vez de nomear a ambiguidade.

Três violações em quinze não é *a maioria*, que era a condição escrita de antemão
para trocar o modelo; então o modelo fica como está e o número é reportado como
veio. As três estavam na disciplina mais difícil — versão e revogação —, que é
exatamente onde uma camada de governança deve ganhar o seu lugar. Os dez casos que
passam e os cinco que falham estão congelados na suíte: resposta gravada mais nota
commitada é um teste de regressão, sem juiz e sem rede.

## Decisões de projeto

### O modelo de embedding é local, multilíngue, fp32 — e tem 470 MB

Local, porque a pergunta também precisa ser embutida em tempo de serviço, e uma
API de embedding exigiria uma chave só para recuperar. Multilíngue, porque o
corpus é texto jurídico em português e um modelo só de inglês degrada em
silêncio. fp32 em vez do export int8 de 118 MB, porque kernels quantizados
diferem entre níveis de instrução da CPU e a mesma passagem seria embutida de
forma diferente em máquinas diferentes — a reprodutibilidade sobre a qual este
projeto é construído terminaria no primeiro pool heterogêneo de nós. O que isso
custa: 470 MB baixados uma vez e verificados por hash, e carregados na imagem do
serviço. Localmente é uma espera; num cluster de verdade são 470 MB de rede e
disco por nó e uma subida de pod mais lenta para cada réplica, que é por que a
resposta de produção é outra (veja abaixo).

### O modelo de geração é o mais barato que serve, de propósito

O modelo fixado é `gpt-5.4-mini-2026-03-17` — um snapshot datado, nunca um alias,
em exatamente um lugar do código. Não porque é barato, embora seja. A tese deste
repositório é que governança, e não qualidade do modelo, é o que torna um LLM
seguro em produção: o contrato que recusa uma afirmação sem citação, o orçamento
que para antes da chamada, a trilha que registra o que foi bloqueado. Se essa
camada pega violações de um modelo pequeno, ela está fazendo trabalho de verdade.
Com um modelo de ponta, a qualidade do próprio modelo mascararia um contrato
fraco, e não haveria como distinguir os dois. Escolher o menor modelo adequado é
uma escolha metodológica, não uma economia.

A condição honesta de reversão: se, ao gravar os casos de avaliação, o mini
produzisse violação de contrato na maioria deles, isso não seria motivo para
trocar em silêncio. Seria um achado, a ser escrito aqui primeiro, e só então um
motivo para mudar o modelo — dizendo o que mudou e quais eram os números antes e
depois.

### Quem diz que uma resposta está certa: uma pessoa, uma vez

Gravar as respostas do modelo dá saídas; dizer se uma saída está certa exige um
corretor, e havia duas opções ruins e uma boa. Um juiz-LLM acrescenta um segundo
componente não determinístico a um projeto cuja tese é determinismo. Um corretor
por regras alcança forma — desfecho, citações, frases-chave — mas não conteúdo.
Então a autora avalia à mão, uma vez: quinze perguntas, um domínio que ela
consegue julgar, e os vereditos commitados ao lado das respostas gravadas
(`eval/generation/`). Dali em diante a avaliação é um teste de regressão —
resposta gravada mais nota commitada — sem juiz e sem rede. As expectativas foram
escritas a partir do texto do corpus antes da rodada viva, para que a gravação não
moldasse aquilo contra o que seria medida; as notas são escritas depois, sobre
conteúdo que o código não julga. Uma nota `fail` é mantida e reportada, não
escondida: é contra ela que a condição de reversão do modelo é medida.

### Três tipos de passagem, porque o corpus guarda três

Um chunk é uma *unidade* da norma — um caput ou um § com o que se aninha nele.
Dois tipos de passagem não são isso, e cada um ganha o seu.

O **aviso de revogação** de um ato revogado é um chunk próprio, porque é a
passagem que uma resposta sobre ato revogado tem de citar e nenhuma pergunta se
parece com ele; a recuperação o anexa por regra, não por similaridade.

O artigo de um ato alterador, carregando **o texto que ele transcreve**, é o
terceiro: *"Art. 1º A Circular nº 3.978 … passa a vigorar com as seguintes
alterações: «Art. 23-A …»"*. Essas transcrições duplicam texto consolidado que já
carrega seu próprio marcador de proveniência, então o movimento óbvio é
descartá-las, e por um tempo foi o que fiz — foi assim que *"O que a Resolução 344
mudou?"* passou a não ter resposta num corpus que a responde literalmente. Agora
são indexadas, sempre unidas ao artigo que as transcreve para que nunca passem
pela norma em si, e ranqueadas abaixo do texto em vigor a menos que a pergunta
nomeie o ato alterador. O cabeçalho de uma passagem dessas diz o que ela é, e o
prompt proíbe citá-la como a redação em vigor.

### O rascunho bloqueado é guardado inteiro, e isso custa alguma privacidade

A trilha de auditoria guarda a pergunta como hash, não como texto. Guarda também,
inteiro, todo rascunho que o contrato bloqueou — porque "o modelo tentou dizer X e
foi parado" é a evidência de que o portão funcionou, e *nada atravessa sem
registro* tem de incluir o que não atravessou. As duas decisões puxam em sentidos
opostos: um rascunho é gerado a partir da pergunta e frequentemente a parafraseia,
de modo que guardar o hash da pergunta protege menos do que parece. Neste corpus
isso não importa — as perguntas são sobre regulação pública e os casos de
avaliação são meus — e o rascunho é retido de propósito. Fica nomeado aqui para
que ninguém precise descobrir sozinho.

## Rodando

Tudo menos o cluster é `make`, e nada aqui chega a uma API paga.

```bash
make test        # o portão: 150 testes, sem rede a modelo nenhum, sem chave
make lint        # ruff
make index       # embute o corpus em var/index (alguns minutos na primeira vez:
                 # baixa o modelo de embedding fixado, ~470 MB, uma vez)
make eval        # recuperação sobre os casos congelados, e o portão de geração
```

Uma pergunta, sem o cluster:

```bash
.venv/bin/python -m eclusa.index search "Quando a Circular 3.978 entra em vigor?"
.venv/bin/uvicorn eclusa.service.app:app --port 8000
curl -s localhost:8000/readyz | python3 -m json.tool
```

### Provando num cluster

```bash
make prove       # sobe o kind, constrói, carrega, aplica, espera a prontidão, pergunta
```

`make prove` cria um cluster `kind`, constrói a imagem, carrega-a com `kind load
docker-image` — ela nunca vem de um registry —, aplica os manifests, espera o
rollout, e então faz ao serviço uma pergunta real e confere a resposta: o
desfecho, uma afirmação, e uma citação que nomeia um documento e um dispositivo. O
pod faz isso **sem rede e sem chave de API**, porque o provedor reproduz as
gravações commitadas a menos que mandem duas vezes ir ao vivo. A mesma sequência
roda no CI a cada push, que é a diferença entre saber Kubernetes e mostrá-lo
rodando.

```bash
make kind-down   # quando terminar
```

O modelo vivo só é alcançado pelo `make record`, que exige `ECLUSA_LIVE=1` e
`OPENAI_API_KEY` no ambiente e para antes de qualquer chamada que levasse o pior
caso da rodada acima de um teto. Gravar os quinze casos de avaliação custa cerca
de cinco centavos de dólar.

## Layout

```
corpus/        manifest.json + raw/ (como capturado) + text/ (o que o sistema lê)
collector/     eclusa/collector: o caminho de atualização do corpus
eclusa/ingest  extração (duas rotas, uma forma) e segmentação com localizadores
eclusa/index   chunking, o modelo de embedding fixado, busca exata, recuperação
               ciente de versão
eclusa/service contrato, orçamento, auditoria, provedor, prompts, o gateway, a app
eclusa/eval    as duas avaliações
prompts/       prompts como artefatos versionados em disco, não strings em funções
eval/          casos congelados, métricas, medições e as respostas gravadas
k8s/           manifests + a configuração do cluster kind
tests/         150 testes
```

## Testes

O portão é determinístico e offline. `pytest` sem argumentos não consegue chamar
uma API paga: o provedor que reproduz gravações é o padrão, o cliente vivo só é
importado quando `ECLUSA_LIVE=1` e uma chave estão ambos postos, e um teste afirma
que o SDK da OpenAI sequer é carregado em modo gravado. Se `pytest` sozinho
pudesse gastar dinheiro, o errado seria o desenho, não a permissão.

O que a suíte guarda, além do usual:

- **Extração**, antes de existir código de LLM: numeração de artigos recuperável,
  monotônica e completa contra contagens conferidas à mão, em quatro leiautes de
  rodapé; o texto commitado byte a byte idêntico ao que as capturas brutas
  extraem, com a versão do poppler afirmada antes, para que uma divergência seja
  nomeada em vez de ficar como um diff inexplicado.
- **O manifesto**: o que o esquema recusa — duas versões em vigor, um documento
  superado apontando para outro ato, um ato revogador fora do corpus, um PDF
  marcado como fonte.
- **Localizadores** nos 21 documentos: incisos correndo I, II, III sob um mesmo
  pai, alíneas a…z e depois aa…, cada nível reiniciando os de baixo.
- **Recuperação**, medida em separado da geração sobre 29 casos congelados, com os
  números mantidos como portão.
- **Os caminhos de falha do contrato**, exercitados em vez de documentados: um
  rascunho que cita passagem não recuperada para a sua requisição, um localizador
  que não é dispositivo dentro do seu chunk, texto superado sem a versão em vigor,
  texto revogado sem a sua revogação, saída que não é JSON, JSON que não é um
  rascunho, um orçamento que para antes da chamada. Todo caminho escreve
  exatamente um registro de auditoria.
- **O serviço**: não pronto antes de o corpus e o índice estarem carregados, e uma
  pergunta gravada respondida de ponta a ponta pela eclusa inteira.

### Dois fluxos de avaliação, e a diferença entre eles

Dizer o que os separa vale mais do que qualquer um deles.

**O portão** roda a cada push e pull request, contra respostas gravadas:
determinístico, sem rede a modelo nenhum, sem chave de API, sem cartão. É isso que
sustenta o badge. CI que depende de um modelo vivo e de um cartão de crédito não
roda, e badge que depende do uptime alheio mente.

**O monitor de deriva** é `workflow_dispatch` apenas. Ele faz as mesmas perguntas
congeladas ao modelo vivo e reporta quanto as respostas se afastaram das gravações
— desfecho, as passagens em que se apoiam, o que o contrato fez — e há quantos
dias as gravações foram feitas, que é o número que diz se a comparação ainda
significa algo. Ele **nunca barra**: um provedor pode atualizar um modelo sem
aviso, e isso é informação a observar, não motivo para derrubar um build. Custa
cerca de cinco centavos por rodada:

```bash
ECLUSA_LIVE=1 OPENAI_API_KEY=... .venv/bin/python -m eclusa.eval drift
```

Ele escreve na própria cassete e na própria trilha, nunca nas gravações que o
portão reproduz.

## Onde isto cresce

- **Um destino durável para a trilha.** No cluster ela é um `emptyDir` e pertence
  ao tempo de vida do pod.
- **Mais corpus.** A fronteira é PLD/FT para instituições supervisionadas pelo
  BCB, e todo ato deliberadamente deixado de fora é um caso de avaliação: a pena
  do crime (lei federal), procedimentos de compra de ouro, setores do COAF, a
  família de câmbio.

## O que eu faria diferente em produção

**Dar ao rascunho bloqueado a mesma política de retenção da pergunta.** Num
sistema que responde perguntas sensíveis, guardar o hash da pergunta e manter o
rascunho não é medida de privacidade; o conteúdo volta pelo rascunho. A política
de retenção — por quanto tempo, quem pode ler, o que é redigido — tem de cobrir os
dois, ou a trilha vaza o que o hash deveria segurar.

**Não assar o modelo de embedding dentro da imagem da aplicação.** 470 MB por
réplica é tolerável no `kind` de um laptop e desperdício num cluster. Duas
alternativas honestas: um init container que busca os arquivos fixados uma vez
para um volume compartilhado, mantendo a imagem da aplicação pequena e puxando o
modelo por nó em vez de por réplica; ou um serviço de embedding próprio, que
também permite fixar e atualizar o modelo independentemente do gateway. As duas
mantêm o mesmo pin — nome, revisão, hashes de arquivo — que este repositório
verifica.

<p align="center">
  Feito por <b>Karla Oliveira</b> · <a href="https://github.com/kabianca">@kabianca</a>
<!-- · <a href="https://www.linkedin.com/in/karlaboliveira/">LinkedIn</a> -->
  <br>
  <sub>Licenciado sob GPL-3.0 · Perguntas e críticas são bem-vindas | abra uma issue.</sub>
</p>
