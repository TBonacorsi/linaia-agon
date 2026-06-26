// ==========================================================
// LINAIA-AGON — Motor de jogo
// Conversa com Python via OSC (porta 57200)
// O HTML faz polling HTTP no Python (porta 8765)
//
// ORDEM DE EXECUÇÃO:
// 1. python3 linaia_server.py   (Terminal — deixa rodando)
// 2. Execute este arquivo inteiro com Ctrl+A, Shift+Enter
// 3. Para iniciar só abrir o HTML e seguir a interface
// ==========================================================

(
s.waitForBoot({

    ~pythonAddr = NetAddr("127.0.0.1", 57200);

    ~matrixAlpha = [[-2,0,0,0],[1,0,-3,-2],[0,-1,1,-2],[0,-1,-2,1]];
    ~matrixBeta  = [[1,-2,-2,3],[1,-1,0,-2],[0,4,-2,-2],[-2,-1,5,1]];
    ~matrixGamma = [[4,-4,2,3],[-1,2,-1,-3],[-1,-1,0,4],[-3,1,5,-2]];

    ~tacticLists = (
        alpha: [\I, \II, \III, \IV],
        beta:  [\V, \VI, \VII, \VIII],
        gamma: [\IX, \X, \XI, \XII]
    );

    ~gameState = (
        battle:       \alpha,
        round:        0,
        scoreLinos:   0,
        scoreApollo:  0,
        waiting:      false,
        segmento:     0
    );

    ~pendingTacticLinos  = nil;
    ~pendingTacticApollo = nil;



    // ── COMUNICAÇÃO COM PYTHON ─────────────────────────
    ~pythonStart = { ~pythonAddr.sendMsg('/linaia/start'); "Python: escuta ATIVA".postln; };
    ~pythonStop  = { ~pythonAddr.sendMsg('/linaia/stop');  "Python: escuta PAUSADA".postln; };

    ~notificarPlacar = {
        ~pythonAddr.sendMsg('/linaia/score', ~gameState[\scoreLinos], ~gameState[\scoreApollo]);
    };

    ~notificarSegmento = { |n|
        ~pythonAddr.sendMsg('/linaia/segment', n);
    };

    ~notificarCenario = { |batalha|
        var cenL = switch(batalha,
            \alpha, "alpha_Linos",
            \beta,  "beta_Linos",
            \gamma, "gamma_Linos"
        );
        var cenA = switch(batalha,
            \alpha, "alpha_Apollon",
            \beta,  "beta_Apollon",
            \gamma, "gamma_Apollon"
        );
        ~pythonAddr.sendMsg('/linaia/scenario', cenL);
        ~pythonAddr.sendMsg('/linaia/scenario', cenA);
        ("Cenário Python → " ++ cenL ++ " / " ++ cenA).postln;
    };


    // ── RECEPTOR OSC (2 canais) ──────────────
    OSCdef(\linaiaTacticLinos, { |msg|
        var taticaNum = msg[2].asInteger;
        var tactList  = ~tacticLists[~gameState[\battle]];
        if(taticaNum >= 1 && { taticaNum <= 4 }, {
            ~pendingTacticLinos = tactList[taticaNum - 1];
            ("Linos → " ++ ~pendingTacticLinos).postln;
        });
    }, '/linaia/tactic/linos');

    OSCdef(\linaiaTacticApollo, { |msg|
        var taticaNum = msg[2].asInteger;
        var tactList  = ~tacticLists[~gameState[\battle]];
        if(taticaNum >= 1 && { taticaNum <= 4 }, {
            ~pendingTacticApollo = tactList[taticaNum - 1];
            ("Apollo → " ++ ~pendingTacticApollo).postln;
        });
    }, '/linaia/tactic/apollo');

    // ── RODADA (COM PERFORMERS) ────────────────────
    ~runRound = { |battleType=\alpha, timeout=12|
        var matrix   = switch(battleType,
            \alpha, ~matrixAlpha, \beta, ~matrixBeta, \gamma, ~matrixGamma);
        var tactList = ~tacticLists[battleType];

        Routine({
            var taticaLinos, taticaApollon, payoff, idxL, idxA;

            ~pendingTacticLinos  = nil;
            ~pendingTacticApollo = nil;
            ~gameState[\waiting] = true;

            ~gameState[\segmento] = ~gameState[\round];
            ~notificarSegmento.(~gameState[\round]);
            ~notificarCenario.(battleType);

            ~pythonStart.();

            ("\n=== Rodada " ++ (~gameState[\round]+1) ++ " | " ++ battleType ++ " ===").postln;

            // Aguarda o tempo da rodada
            timeout.wait;

            // PARA Python
            ~pythonStop.();
            ~gameState[\waiting] = false;

            // Pega as táticas classificadas (fallback = aleatório)
            taticaLinos  = ~pendingTacticLinos  ?? { tactList.choose };
            taticaApollon = ~pendingTacticApollo ?? { tactList.choose };

            ("Linos:  " ++ taticaLinos).postln;
            ("Apollon: " ++ taticaApollon).postln;

            // Calcula payoff
            idxL = tactList.indexOf(taticaLinos) ? 0;
            idxA = tactList.indexOf(taticaApollon) ? 0;
            payoff = matrix[idxL][idxA];

            if(payoff > 0) {
                ~gameState[\scoreLinos] = ~gameState[\scoreLinos] + payoff;
                ("Linos +" ++ payoff).postln;
            };
            if(payoff < 0) {
                ~gameState[\scoreApollo] = ~gameState[\scoreApollo] + payoff.abs;
                ("Apollon +" ++ payoff.abs).postln;
            };

            ~gameState[\round] = ~gameState[\round] + 1;
            ~notificarPlacar.();

            ("Placar: Linos " ++ ~gameState[\scoreLinos]
             ++ " | Apollon " ++ ~gameState[\scoreApollo]).postln;

        }).play;
    };

    // ── MUDAR DE BATALHA ──────────────────────────────
    ~proximaBatalha = {
        var ordem = [\alpha, \beta, \gamma];
        var idx = ordem.indexOf(~gameState[\battle]);
        if(idx < 2) {
            ~gameState[\battle] = ordem[idx + 1];
            ~notificarCenario.(~gameState[\battle]);
            ("⚔Próxima batalha: " ++ ~gameState[\battle]).postln;
        } {
            "Fim da campanha!".postln;
        };
    };

    "=== LINAIA-AGON (tempo real) carregado ===".postln;
    "Comandos:".postln;
    "  ~runRound.(\\alpha, 12)   // Rodada Alpha, 12 segundos".postln;
    "  ~proximaBatalha.()       // Avança para próxima batalha".postln;
});
)

// Iniciar primeira rodada
~runRound.(\alpha, 12);

~runRound.(\beta, 12);