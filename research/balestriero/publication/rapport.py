"""Generate the research brief from the three sealed synthetic comparisons."""
import json
from pathlib import Path
import sys

from reportlab.lib.pagesizes import A4
from reportlab.platypus import PageBreak,SimpleDocTemplate,Spacer
from documentation.bilan import p,fr,table,header,callout

ROOT=Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT/path).read_text())


def sign(x,d=2):
    return ("+" if x>0 else "")+fr(x,d)


def ic(x,d=2):
    return "["+sign(x[0],d)+" à "+sign(x[1],d)+"]"


def ratio(r,d=1):
    return "n. e." if r["value"] is None else fr(100*r["value"],d)+" %"


def make(dest):
    cf=load("cf/resultats/resultats.json")
    hier=load("hierarchie/resultats/verdict.json")
    projection=load("contraintes/resultats/verdict.json")
    ad=load("hierarchie/resultats/ajustement.json")
    c=cf["primary"];strata=cf["by_condition"];hh=hier["arms"]
    def H72(arm):
        return hh[arm]["horizon"]["72"]
    def cell(feed="full",clock=12,h=4,model="jepa19"):
        return strata[f"{feed}/{clock:02d}/{h}/{model}"]
    benefit=c["mae_factual_copy_minus_anchor"];absolute=c["mae_base_minus_anchor"]
    winner=hier["demonstrated_operational_improvement"]
    s=[p("HOSPITALOS  /  COMPARAISON D’ARCHITECTURES","ey"),
       p("Prévoir à 8 h, comprendre à 16 h","h"),
       p("Nous avons testé deux idées de Randall Balestriero et de ses coauteurs sur 64 hôpitaux synthétiques. L’une utilise le relevé de 16 h pour estimer la file qu’aurait produite une autre affectation à midi. L’autre choisit un renfort à 8 h en deux temps. Un second panel indépendant de 32 hôpitaux évalue une correction des incohérences de stocks."),
       callout(f"La prévision de midi fait une erreur de {fr(c['base_mae'],3)} patient par unité sur la file de 16 h. Après réception du relevé, réutiliser l’écart observé ramène cette erreur à {fr(c['anchor_mae'],3)} avec le JEPA et à {fr(strata['full/12/4/ssm']['anchor_mae'],3)} avec le moteur structuré seul."),
       p("Reconstruction de la file de transfert à 16 h","s"),
       table(["Estimation pour une autre décision prise à midi","Erreur absolue¹","R² du niveau"],[
              ["Prévision HospitalOS gelée",fr(c["base_mae"],3),fr(100*c["level_r2"]["base"],2)+" %"],
              ["Résidu du même épisode",fr(c["anchor_mae"],3),fr(100*c["level_r2"]["anchor"],2)+" %"],
              ["Copie de la file factuelle",fr(c["copy_mae"],3),fr(100*c["level_r2"]["copy"],2)+" %"],
              ["Résidu d’un autre épisode du même hôpital",fr(c["placebo_mae"],3),fr(100*c["level_r2"]["placebo"],2)+" %"]],[281,109,107]),
       Spacer(1,5),p("¹ Nombre de patients par unité, moyenné sur les alternatives distinctes, les épisodes puis les établissements. Une unité peut avoir une valeur fractionnaire dans ce simulateur de flux continus. Chaque comparaison utilise le même recensement de départ et les mêmes événements futurs. Le critère primaire utilise le flux complet et la graine 19.","note"),
       p(f"Face à la prévision de midi, la baisse moyenne d’erreur est de {fr(absolute['value'],3)} patient par unité, IC 95 % de {ic(absolute['ci95'],3)}. Face à la copie du factuel, elle est de {sign(benefit['value'],3)}, IC 95 % de {ic(benefit['ci95'],3)}."),
       p("Ce que le papier mesure","s"),
       p("Le passage de 38–46 % à 86–96 % publié le 18 novembre concerne le R² sur quatre simulateurs visuels. Les auteurs exigeaient notamment qu’une copie du factuel reste sous 60 % de R² sur leur population qualifiée. Sur la file hospitalière, la copie atteint déjà 90,66 %. La MAE face à cette copie est donc le comparateur le plus informatif ici.","note"),PageBreak()]
    z=c["latent_rmse"];ssm=cell(model="ssm")
    s+=[p("APRÈS OBSERVATION  /  DONNÉES DISPONIBLES","ey"),p("Ce que le recensement permet de corriger","h"),
        p("Le calcul part de la file effectivement observée sous la décision prise. Il ajoute la différence que le modèle de midi avait prédite entre l’action alternative et cette décision. Une même correction est donc appliquée à toutes les options d’une unité. L’écart entre deux actions et leur ordre pour minimiser la somme des files restent identiques."),
        p("Effet de la qualité du flux","s")]
    rows=[]
    for f,label in (("full","Complet"),("partial","Partiel"),("delayed","Retardé de 2 h")):
        o=cell(f)
        rows.append([label,fr(100*o["observed_fraction"],1)+" %",fr(o["base_mae"],3),fr(o["ontime_mae"],3),fr(o["anchor_mae"],3)])
    s+=[table(["Flux de l’hôpital","Stocks visibles¹","Avant relevé","À 16 h","À réception"],rows,[122,97,96,91,91]),
        Spacer(1,5),p("¹ Part des cinq composantes du recensement disponibles dans le relevé. Les cellules d’erreur concernent les patients en attente de transfert par unité à 16 h. Dans la condition retardée, le relevé de 16 h devient consultable à 18 h. Les composantes absentes conservent leur prévision initiale.","note"),
        p("Quel composant apporte le signal ?","s"),
        p(f"Sur la physique structurée seule, la même correction donne une erreur de {fr(ssm['anchor_mae'],3)} patient par unité, contre {fr(ssm['base_mae'],3)} avant observation. Pour le JEPA historique, les trois graines donnent des erreurs corrigées de "+", ".join(fr(cell(model='jepa'+str(seed))['anchor_mae'],3) for seed in (19,37,71))+" patient par unité."),
        p(f"Dans les 24 coordonnées latentes de la graine 19, les erreurs quadratiques moyennes prises à la racine valent {fr(z['base'],4)} avant correction, {fr(z['anchor'],4)} après correction et {fr(z['copy'],4)} pour la copie du latent factuel. Ces valeurs sont exprimées dans l’espace de représentation du modèle."),
        p(f"L’erreur absolue sur l’effet de changer d’action est de {fr(c['contrast_mae'],3)} patient par unité. Une prévision d’effet systématiquement nul donne {fr(c['null_contrast_mae'],3)}. Lorsque l’action change réellement la file d’au moins 0,05 patient, le modèle fait une erreur de {fr(c['conditional_mae_effect_changed']['value'],3)} contre {fr(c['conditional_null_effect_changed']['value'],3)} pour l’effet nul."),
        p("Un usage possible pour le cadre","s"),
        p(f"Pour {c['goal_count']} cibles réalisables construites après coup dans le simulateur, le choix d’action qui retrouve la répartition cible des files passe de {ratio(c['goal_hit_rate']['base'])} avec la prévision de midi à {ratio(c['goal_hit_rate']['anchor'])} avec le relevé de 16 h. Cette comparaison répond à une question rétrospective sur une cible donnée.","note"),PageBreak()]
    log=H72("hierarchique");ac=hh["hierarchique"]["active_delivered_ge_1h_already_planned"]
    decision=("La hiérarchie franchit les critères opérationnels de cet essai synthétique." if winner else
              "Le planificateur horaire reste la référence opérationnelle de cet essai.")
    s+=[p("AVANT ACTION  /  COMPARAISON DE PLANIFICATION","ey"),p("La hiérarchie recommande-t-elle un meilleur renfort ?","h"),
        p("À 8 h, l’étage haut du candidat évalue les familles de ressources à 72 h et émet un sous-objectif à 24 h. L’étage bas choisit l’unité et, pour un prêt infirmier, le donneur. L’ablation plate évalue directement les affectations à partir des mêmes informations. Chaque branche peut conserver le plan horaire. Les conséquences sont rejouées en boucle fermée."),
        callout(decision),p(f"Résultats appariés sur {fr(hier['contexts'],0)} situations","s")]
    matrix=[]
    for key,label in (("j7_livre","Sélecteur J7 livré"),("plat","Adaptation plate"),("hierarchique","Adaptation hiérarchique"),("hierarchique_brut","Hiérarchique avant le dernier filtre")):
        v=H72(key);t=v["gain_transfer_h"];a=hh[key]["active_delivered_ge_1h_already_planned"];matrix.append([label,fr(a[0],0),
                sign(t["mean"]),ic(t["cluster_95"]),str(v["site_ward_breaches"])+" / "+str(hier["n_site_wards"])])
    s+=[table(["Politique","Actions","Gain¹ (h)","IC à 95 %","Unités > 1 %²"],matrix,[159,57,71,112,98]),Spacer(1,5),
        p("¹ Heures-patients d’attente de transfert évitées à 72 h face au planning horaire. Un gain positif correspond à une diminution de l’attente. ² Chaque unité a sa propre référence d’attente de lit, de minutes infirmières et de minutes aides-soignantes non couvertes. Les trois seuils sont vérifiés séparément.","note")]
    comp=hier["paired_cluster_contrasts_h72"]["hierarchique_vs_plat"]
    s+=[p(f"L’écart hiérarchique moins plat vaut {sign(comp['mean'])} heure-patient, IC 95 % de {ic(comp['cluster_95'])}. La hiérarchie a proposé {int(ac[0])} actions, dont {int(ac[1])} ont mobilisé une ressource pendant au moins une heure. Les politiques partagent le catalogue public et les contrôles de disponibilité."),
        p("Ce qui a été entraîné","s"),
        p(f"Les poids de l’adaptation utilisent {len(ad['fit_sites'])} hôpitaux, et la calibration du dernier filtre {len(ad['calibration_sites'])} autres. Les deux variantes ont chacune {fr(ad['learned_prediction_coefficients']['flat'],0)} coefficients de prédiction. La version plate a un latent de 8 dimensions. La version hiérarchique ajoute un latent lent de 4 dimensions et une décision par famille. Les deux utilisent des cibles de transitions simulées appariées.","note"),PageBreak()]
    obs=projection["primary"];ss=projection["conditions"]["full/12/4/ssm"]
    s+=[p("SECOND PANEL  /  LIMITES  /  SOURCES","ey"),p("Des stocks compatibles avec les lits disponibles","h"),
        p("Sur le premier panel, le résidu additif produit parfois un effectif négatif ou dépasse le nombre de lits. Nous avons ajouté une projection sur les stocks réalisables de chaque unité, puis figé cette correction avant un essai sur 32 autres hôpitaux. Elle conserve chaque valeur publiée dans la branche factuelle."),
        callout(f"Sur ce nouveau panel, les états impossibles du JEPA passent de {fr(100*obs['raw_invalid'],1)} % à {fr(100*obs['projected_invalid'],0)} %. L’erreur sur la file de transfert passe de {fr(obs['raw_mae'],4)} à {fr(obs['projected_mae'],4)} patient par unité. Avec le moteur structuré, elle atteint {fr(ss['projected_mae'],4)} après projection."),
        p(f"Critère principal à 16 h, flux complet. La différence d’erreur avant moins après projection vaut {sign(obs['lower_mae_vs_anchor']['value'],4)}, IC 95 % de {ic(obs['lower_mae_vs_anchor']['ci95'],4)}. La projection inverse {obs['strict_rank_reversals']} des {fr(obs['strict_pairs_compared'],0)} comparaisons strictes entre actions. Ces calculs utilisent le relevé reçu après la décision.","note"),
        p("Portée des résultats","s"),
        p("Les poids JEPA historiques avaient déjà appris sur des différences entre actions simulées. Le nouvel ancrage les utilise sans réentraînement. Les contraintes portent sur cinq stocks par unité. Le transfert entre services, les mécanismes de saturation et la causalité sur données hospitalières réelles demandent des validations spécifiques.","note"),
        p("La hiérarchie est une adaptation tabulaire en deux étages pour un seul poste. Le moteur avance d’heure en heure. Les résolutions de quinze minutes et les séquences de plusieurs décisions sous un même objectif restent à tester. Les intervalles présentés portent sur des établissements synthétiques.","note"),
        p("Travaux vérifiés","s"),
        table(["Publication","Apport et place dans cet essai"],[
             ["Counterfactual World Models\narXiv 2611.24778", "Résidu factuel réutilisé après observation. Évalué sur les états et les files du simulateur."],
             ["H-JEPA\narXiv 2610.06805", "Planification avec plusieurs espaces latents et sous-objectifs. Adaptation opérationnelle comparée à un modèle plat."],
             ["Semigroup-JEPA\narXiv 2609.10464","Cohérence des dynamiques composées sur plusieurs pas. Piste pour les transitions hospitalières."],
             ["Causal-JEPA\narXiv 2602.11389","Masquage latent au niveau des objets pour apprendre leurs interactions. Piste pour les échanges entre unités."],
             ["LeNEPA\narXiv 2607.00958","Prévision autosupervisée de la représentation temporelle suivante, sans augmentation. Piste pour les séries hospitalières."]],[178,319]),
        Spacer(1,8),p("Les liens vers les articles, le dépôt des auteurs et les commandes de reproduction sont dans le fichier README de l’archive. Les résultats ci-dessus proviennent exclusivement d’hôpitaux synthétiques.","note")]
    doc=SimpleDocTemplate(str(dest),pagesize=A4,topMargin=63,bottomMargin=49,leftMargin=48,rightMargin=48,
                          title="HospitalOS | Contrefactuel et planification hiérarchique",author="HospitalOS")
    doc.build(s,onFirstPage=header,onLaterPages=header)


if __name__=="__main__":make(sys.argv[1])
