"""
Banque de formulations des notes synthétiques (v0.4), rédigée à la main.

Conventions de gabarit :
  {Mme} -> « Mme » ou « M. » ; {e} -> « e » au féminin ; {il} -> « elle » / « il » ;
  {Il} -> « Elle » / « Il » ; {le} -> « la » / « le » ; {n}, {k}, {m}, {d} : petits nombres tirés ;
  {cote} -> « droite » / « gauche » ; {age} -> âge ; {lui} -> « elle » / « lui » ;
  {Veuf}, {conjoint} (« son époux » pour une patiente, « son épouse » pour un patient),
  {Conjoint_aidant}, {Conjoint_present}, {ce}, {fumeur} : accords qui ne se réduisent pas à un « e ».

Deux banques pour les champs qui comptent (social, cognition, autonomie) :
  PRINCIPALE, utilisée toute l'année ;
  HORS_VOCABULAIRE, utilisée en plus sur la période de test, pour mesurer la robustesse
  d'un extracteur à des formulations qu'il n'a pas vues.

Aucune formulation ne parle de date de sortie, de durée de séjour ni de destination réalisée.
"""

UNITES_LIBELLE = {
    "MED_POLY": ["médecine polyvalente", "médecine interne", "méd. polyvalente"],
    "CSG": ["court séjour gériatrique", "gériatrie aiguë", "CSG"],
    "PNEUMO": ["pneumologie", "pneumo"],
    "CARDIO": ["cardiologie", "cardio", "USIC puis cardiologie"],
}

# --------------------------------------------------------------------------
# Motifs : unités, affinités (oxygène, isolement, durée, âge, incertitude), textes
# --------------------------------------------------------------------------
MOTIFS = {
    "pneumopathie": dict(
        unites={"MED_POLY": 3, "PNEUMO": 3, "CSG": 1.5}, oxy=2.5, iso=1.0, los=0.0, age=0.0, incert=0.3,
        court=["Dyspnée fébrile", "Toux fébrile", "Fièvre + toux productive", "PAC ?"],
        hdm=["Toux productive depuis {n} jours, fièvre à 38,{d} °C, dyspnée d'effort croissante.",
             "Depuis {n} j, frissons, expectorations purulentes et majoration de la dyspnée.",
             "Fièvre depuis {n} j malgré amoxicilline débutée par le médecin traitant, désaturation ce jour.",
             "Tableau infectieux respiratoire évoluant depuis {n} jours, adressé{e} par SOS Médecins."],
        examen=["Crépitants en base {cote}, polypnée à 2{d}/min.",
                "Foyer de crépitants base {cote}, pas de signe de lutte.",
                "Auscultation : crépitants {cotem}s, sueurs, FR 2{d}."],
        diag=["Pneumopathie aiguë communautaire {cote}.", "PAC lobaire inférieure {cote}."],
        hypo=["Probable pneumopathie {cote}, à confirmer sur la radio.",
              "Suspicion de pneumopathie, DD décompensation cardiaque."],
        imagerie=["TDM thoracique", "radio thoracique de face"], avis=["avis infectiologique"]),
    "infection_urinaire": dict(
        unites={"MED_POLY": 3, "CSG": 2}, oxy=0.3, iso=0.8, los=-0.2, age=0.3, incert=0.3,
        court=["Fièvre + brûlures mictionnelles", "Pyélonéphrite", "Fièvre, douleur lombaire", "IU fébrile"],
        hdm=["Brûlures mictionnelles depuis {n} j, puis fièvre à 39 °C et frissons ce matin.",
             "Douleur lombaire {cote} fébrile depuis {n} jours, nausées.",
             "Pollakiurie et fièvre, BU positive aux nitrites chez le MT."],
        examen=["Douleur à l'ébranlement lombaire {cote}.", "Abdomen souple, globe vésical non retrouvé."],
        diag=["Pyélonéphrite aiguë {cote}.", "Infection urinaire fébrile."],
        hypo=["Probable pyélonéphrite, ECBU en cours.", "Sepsis d'origine urinaire probable."],
        imagerie=["échographie rénale", "uro-scanner"], avis=["avis urologique"]),
    "aeg": dict(
        unites={"MED_POLY": 2.5, "CSG": 3}, oxy=0.2, iso=0.3, los=1.0, age=0.6, incert=0.8,
        court=["AEG", "Altération de l'état général", "Asthénie, anorexie", "AEG + amaigrissement"],
        hdm=["Asthénie, anorexie et amaigrissement de {k} kg en {m} mois.",
             "Dégradation progressive depuis {m} mois : ne s'alimente plus, reste au lit.",
             "Adressé{e} par le MT pour AEG avec perte de {k} kg, bilan ambulatoire non contributif."],
        examen=["Pas de point d'appel infectieux, BMI à 1{d}.", "Patient{e} cachectique, examen sans particularité."],
        diag=["AEG sur néoplasie connue en progression."],
        hypo=["AEG d'origine indéterminée, bilan étiologique à poursuivre.",
              "AEG, néoplasie à éliminer.", "AEG : cause néoplasique ? dépressive ? iatrogène ?"],
        imagerie=["TDM thoraco-abdomino-pelvien", "TDM TAP"], avis=["avis gastro-entérologique", "avis oncologique"]),
    "chute": dict(
        unites={"CSG": 4, "MED_POLY": 2}, oxy=0.2, iso=0.3, los=0.3, age=1.0, incert=0.3,
        court=["Chute à domicile", "Chute mécanique", "Chute avec station au sol prolongée", "Chute"],
        hdm=["Retrouvé{e} au sol, station au sol estimée à {n} h.",
             "Chute mécanique en se levant la nuit, pas de perte de connaissance.",
             "Chute dans l'escalier, se plaint de la hanche {cote}.",
             "{n}e chute en un mois selon l'entourage, cette fois incapable de se relever."],
        examen=["Hématome frontal, pas de déficit sensitivo-moteur.", "Douleur de hanche {cote}, mobilisation possible.",
                "Dermabrasions des avant-bras, pas de signe de fracture."],
        diag=["Chute mécanique sans traumatisme grave.", "Chute avec station au sol prolongée, rhabdomyolyse modérée."],
        hypo=["Chute : cause mécanique probable, malaise non exclu.", "Chute d'origine multifactorielle ?"],
        imagerie=["TDM cérébral", "radio du bassin"], avis=["avis gériatrique", "avis orthopédique"]),
    "confusion": dict(
        unites={"CSG": 4, "MED_POLY": 1}, oxy=0.3, iso=0.3, los=0.5, age=1.0, incert=0.9,
        court=["Confusion aiguë", "Syndrome confusionnel", "Agitation, désorientation", "Troubles du comportement"],
        hdm=["Désorientation et agitation depuis {n} j selon la famille, inversion du rythme nycthéméral.",
             "Propos incohérents depuis hier soir, a tenté de sortir de chez {lui} la nuit.",
             "Somnolence alternant avec agitation depuis {n} jours."],
        examen=["Désorienté{e} dans le temps et l'espace, pas de déficit focal.", "Inattention, pas de syndrome méningé."],
        diag=["Syndrome confusionnel sur rétention aiguë d'urines."],
        hypo=["Syndrome confusionnel, cause probablement infectieuse (urinaire ?).",
              "Confusion aiguë multifactorielle : iatrogénie ? fécalome ? infection ?"],
        imagerie=["TDM cérébral"], avis=["avis neurologique", "avis gériatrique"]),
    "inhalation": dict(
        unites={"CSG": 2, "PNEUMO": 1}, oxy=2.0, iso=0.3, los=0.5, age=1.0, incert=0.4,
        court=["Pneumopathie d'inhalation", "Fausse route + fièvre", "Toux au repas puis fièvre"],
        hdm=["Toux lors des repas depuis quelques semaines, fièvre depuis {n} j.",
             "Fausse route alimentaire hier soir puis désaturation."],
        examen=["Crépitants base droite, encombrement bronchique."],
        diag=["Pneumopathie d'inhalation base droite."],
        hypo=["Probable pneumopathie d'inhalation, troubles de déglutition à explorer."],
        imagerie=["TDM thoracique"], avis=["avis ORL (déglutition)", "avis orthophonique"]),
    "deshydratation": dict(
        unites={"CSG": 2, "MED_POLY": 1}, oxy=0.1, iso=0.3, los=-0.2, age=1.0, incert=0.3,
        court=["Déshydratation", "Hypernatrémie", "Déshydratation sur canicule"],
        hdm=["Apports hydriques très faibles depuis {n} j, chaleur au domicile.",
             "Somnolence, bouche sèche, n'a presque pas bu depuis {n} jours."],
        examen=["Muqueuses sèches, pli cutané persistant."],
        diag=["Déshydratation extracellulaire, IRA fonctionnelle."],
        hypo=["Déshydratation, cause infectieuse à éliminer."],
        imagerie=["échographie rénale"], avis=["avis néphrologique"]),
    "hyponatremie": dict(
        unites={"MED_POLY": 1.5, "CSG": 1}, oxy=0.1, iso=0.2, los=0.0, age=0.6, incert=0.5,
        court=["Hyponatrémie", "Confusion + hyponatrémie", "Na bas"],
        hdm=["Nausées et troubles de la marche, natrémie à 12{d} mmol/L au labo de ville.",
             "Ralentissement depuis {n} j, hyponatrémie découverte sur bilan systématique."],
        examen=["Examen neurologique sans déficit, euvolémique."],
        diag=["Hyponatrémie à 12{d} mmol/L d'origine médicamenteuse (thiazidique)."],
        hypo=["Hyponatrémie, SIADH ? potomanie ? iatrogénie ?"],
        imagerie=["TDM cérébral"], avis=["avis néphrologique"]),
    "diabete": dict(
        unites={"MED_POLY": 1.5}, oxy=0.1, iso=0.2, los=-0.2, age=-0.2, incert=0.2,
        court=["Déséquilibre glycémique", "Hyperglycémie", "Décompensation diabétique"],
        hdm=["Glycémies capillaires > 4 g/L depuis {n} j, polyurie, polydipsie.",
             "Arrêt de l'insuline depuis {n} j (oubli)."],
        examen=["Déshydratation modérée, pas de trouble de conscience."],
        diag=["Décompensation hyperglycémique sans cétose."],
        hypo=["Décompensation diabétique, facteur déclenchant infectieux ?"],
        imagerie=["radio thoracique"], avis=["avis diabétologique"]),
    "erysipele": dict(
        unites={"MED_POLY": 1.5}, oxy=0.1, iso=0.8, los=0.0, age=0.2, incert=0.3,
        court=["Grosse jambe rouge fébrile", "Érysipèle", "Dermohypodermite"],
        hdm=["Placard inflammatoire de la jambe {cote} depuis {n} j, fièvre.",
             "Rougeur et douleur de jambe {cote} d'extension rapide, porte d'entrée intertrigo."],
        examen=["Placard érythémateux chaud, bords nets, pas de crépitation."],
        diag=["Érysipèle de jambe {cote}."],
        hypo=["Dermohypodermite bactérienne, TVP à éliminer."],
        imagerie=["écho-doppler veineux"], avis=["avis dermatologique"]),
    "anemie": dict(
        unites={"MED_POLY": 1.5, "CSG": 0.8}, oxy=0.2, iso=0.1, los=0.3, age=0.4, incert=0.6,
        court=["Anémie", "Hb basse", "Asthénie + anémie"],
        hdm=["Asthénie et dyspnée d'effort, Hb à {d},{n} g/dL au bilan de ville.",
             "Méléna il y a {n} jours, sous anticoagulant."],
        examen=["Pâleur cutanéo-muqueuse, TR : selles noires."],
        diag=["Anémie microcytaire par carence martiale."],
        hypo=["Anémie, saignement digestif occulte ?"],
        imagerie=["TDM abdominal"], avis=["avis gastro-entérologique"]),
    "malaise": dict(
        unites={"MED_POLY": 1.5, "CSG": 1, "CARDIO": 1}, oxy=0.1, iso=0.1, los=-0.3, age=0.4, incert=0.9,
        court=["Malaise", "Malaise sans PC", "Lipothymie"],
        hdm=["Malaise en se levant avec sensation de dérobement des jambes, pas de PC.",
             "Malaise brutal au domicile, récupération rapide."],
        examen=["Hypotension orthostatique, reste sans particularité."],
        diag=["Malaise sur hypotension orthostatique iatrogène."],
        hypo=["Malaise : vagal ? orthostatique ? rythmique ?", "Malaise inexpliqué, cause cardiaque à éliminer."],
        imagerie=["TDM cérébral"], avis=["avis cardiologique"]),
    "bpco": dict(
        unites={"PNEUMO": 4}, oxy=3.0, iso=0.2, los=0.3, age=0.2, incert=0.2,
        court=["Exacerbation de BPCO", "EABPCO", "Dyspnée chez BPCO", "Décompensation respiratoire"],
        hdm=["Majoration de la dyspnée et des expectorations depuis {n} jours, purulence.",
             "BPCO sous OLD, majoration de la dyspnée de repos depuis {n} j."],
        examen=["Sibilants diffus, tirage sus-claviculaire.", "Freinage expiratoire, polypnée à 2{d}/min."],
        diag=["Exacerbation de BPCO d'origine infectieuse."],
        hypo=["Exacerbation de BPCO, pneumopathie associée ?"],
        imagerie=["TDM thoracique"], avis=["avis cardiologique (cœur pulmonaire ?)"]),
    "embolie": dict(
        unites={"PNEUMO": 2, "CARDIO": 0.5}, oxy=1.5, iso=0.1, los=0.0, age=-0.2, incert=0.6,
        court=["Dyspnée + douleur thoracique", "Suspicion d'EP", "EP"],
        hdm=["Dyspnée brutale et douleur basithoracique {cote} depuis ce matin.",
             "Dyspnée d'aggravation progressive après immobilisation pour entorse."],
        examen=["Tachycardie à 1{d}0/min, mollet {cotem} douloureux."],
        diag=["Embolie pulmonaire bilatérale sans signe de gravité."],
        hypo=["Suspicion d'embolie pulmonaire, score de Wells intermédiaire."],
        imagerie=["angioscanner thoracique"], avis=["avis médecine vasculaire"]),
    "epanchement": dict(
        unites={"PNEUMO": 1.5}, oxy=1.2, iso=0.1, los=0.6, age=0.2, incert=0.7,
        court=["Épanchement pleural", "Dyspnée, épanchement {cotem}"],
        hdm=["Dyspnée d'effort progressive depuis {m} semaines, matité {cote}."],
        examen=["Matité de la base {cote}, abolition du murmure vésiculaire."],
        diag=["Épanchement pleural {cotem} abondant."],
        hypo=["Épanchement pleural {cotem} : néoplasique ? infectieux ? cardiaque ?"],
        imagerie=["échographie pleurale", "TDM thoracique"], avis=["avis chirurgie thoracique"]),
    "neoplasie_pulm": dict(
        unites={"PNEUMO": 1.5}, oxy=0.8, iso=0.1, los=1.2, age=0.0, incert=0.8,
        court=["Opacité pulmonaire suspecte", "Hémoptysie", "Nodule + AEG"],
        hdm=["Hémoptysies de faible abondance depuis {n} j chez un{e} {fumeur} à 40 PA.",
             "Découverte d'une opacité hilaire {cote} sur une radio faite pour toux persistante."],
        examen=["Hippocratisme digital, adénopathie sus-claviculaire {cote}."],
        diag=["Carcinome bronchique connu, progression."],
        hypo=["Opacité suspecte de néoplasie, à documenter.", "Suspicion de néoplasie pulmonaire."],
        imagerie=["TEP-scanner", "TDM thoracique injecté"], avis=["avis oncologique", "avis RCP thoracique"]),
    "grippe": dict(
        unites={"PNEUMO": 1.5, "MED_POLY": 1, "CSG": 0.8}, oxy=1.5, iso=4.0, los=-0.2, age=0.0, incert=0.3,
        court=["Syndrome grippal hypoxémiant", "Grippe A", "COVID-19", "Virose respiratoire"],
        hdm=["Fièvre, myalgies et toux depuis {n} jours, contage familial.",
             "Syndrome grippal depuis {n} j, désaturation ce jour."],
        examen=["Crépitants diffus, polypnée."],
        diag=["Grippe A confirmée (PCR).", "COVID-19 confirmé (PCR)."],
        hypo=["Virose respiratoire probable, PCR en cours."],
        imagerie=["TDM thoracique"], avis=["avis infectiologique"]),
    "asthme": dict(
        unites={"PNEUMO": 0.8}, oxy=1.5, iso=0.1, los=-0.5, age=-1.0, incert=0.1,
        court=["Asthme aigu", "Crise d'asthme sévère"],
        hdm=["Crise d'asthme ne cédant pas sous Ventoline depuis hier."],
        examen=["Sibilants diffus, DEP à 1{d}0 L/min."],
        diag=["Asthme aigu grave."], hypo=["Exacerbation d'asthme, facteur déclenchant viral ?"],
        imagerie=["radio thoracique"], avis=["avis allergologique"]),
    "insuffisance_cardiaque": dict(
        unites={"CARDIO": 4, "CSG": 1.5, "MED_POLY": 1}, oxy=2.0, iso=0.1, los=0.6, age=0.6, incert=0.3,
        court=["Décompensation cardiaque", "ICA", "Dyspnée + OMI", "OAP"],
        hdm=["Prise de poids de {k} kg en {m} semaine(s), orthopnée et OMI.",
             "Dyspnée de décubitus depuis {n} nuits, oublis de furosémide.",
             "Majoration des œdèmes des membres inférieurs, dyspnée au moindre effort."],
        examen=["Crépitants bilatéraux, OMI prenant le godet, TJ.", "Crépitants aux deux bases, reflux hépato-jugulaire."],
        diag=["Insuffisance cardiaque aiguë sur cardiopathie ischémique.", "OAP sur poussée hypertensive."],
        hypo=["Décompensation cardiaque, facteur déclenchant à préciser (FA ? écart de régime ?)."],
        imagerie=["échographie cardiaque (ETT)"], avis=["avis rythmologique"]),
    "fa": dict(
        unites={"CARDIO": 2.5}, oxy=0.3, iso=0.1, los=-0.3, age=0.3, incert=0.2,
        court=["FA rapide", "Palpitations", "Tachyarythmie"],
        hdm=["Palpitations depuis {n} jours, dyspnée d'effort.", "FA découverte lors d'une consultation de routine, FC 1{d}0."],
        examen=["Cœur irrégulier à 1{d}0/min, pas de signe d'IC."],
        diag=["FA rapide de découverte récente."], hypo=["Tachycardie irrégulière, FA probable, ECG à relire."],
        imagerie=["échographie cardiaque (ETT)"], avis=["avis rythmologique"]),
    "sca": dict(
        unites={"CARDIO": 2.5}, oxy=0.4, iso=0.1, los=-0.1, age=-0.2, incert=0.5,
        court=["Douleur thoracique", "SCA ST-", "Douleur thoracique + troponine positive"],
        hdm=["Douleur rétrosternale constrictive à l'effort depuis {n} j, ce jour au repos.",
             "Douleur thoracique de {n} h, troponine à 1{d}0 ng/L."],
        examen=["Examen cardiovasculaire normal, pas de signe d'IC."],
        diag=["SCA ST- à risque intermédiaire."],
        hypo=["Douleur thoracique, SCA non exclu, cycle de troponine en cours."],
        imagerie=["coronarographie"], avis=["avis cardiologie interventionnelle"]),
    "syncope": dict(
        unites={"CARDIO": 1.5, "MED_POLY": 0.5}, oxy=0.1, iso=0.1, los=-0.3, age=0.3, incert=0.9,
        court=["Syncope", "PC brève", "Perte de connaissance"],
        hdm=["Perte de connaissance brève sans prodrome, traumatisme facial.",
             "Syncope à l'effort, récupération immédiate."],
        examen=["Plaie de l'arcade, souffle systolique 2/6."],
        diag=["Syncope sur BAV paroxystique."],
        hypo=["Syncope : rythmique ? réflexe ? orthostatique ?"],
        imagerie=["TDM cérébral"], avis=["avis neurologique"]),
    "bav": dict(
        unites={"CARDIO": 1.0}, oxy=0.1, iso=0.1, los=0.0, age=0.6, incert=0.2,
        court=["Bradycardie", "BAV complet", "BAV de haut degré"],
        hdm=["Asthénie et lipothymies depuis {n} j, FC à 3{d}/min chez le MT."],
        examen=["Bradycardie régulière à 3{d}/min, bien tolérée."],
        diag=["BAV complet."], hypo=["Bradycardie, BAV de haut degré probable, iatrogénie ?"],
        imagerie=["échographie cardiaque (ETT)"], avis=["avis rythmologique (stimulateur)"]),
}

CAUSES_ISOLEMENT = [
    ("contact", "Précautions complémentaires contact (BMR connue, EBLSE)."),
    ("contact", "Isolement contact : portage d'entérobactérie BLSE."),
    ("contact", "Clostridioides difficile : précautions contact renforcées."),
    ("gouttelettes", "Précautions gouttelettes (grippe A)."),
    ("gouttelettes", "Isolement gouttelettes, PCR COVID positive."),
    ("air", "Précautions air : suspicion de tuberculose, BK crachats x3."),
    ("contact", "Gale : isolement contact."),
]

# --------------------------------------------------------------------------
# Antécédents et traitements
# --------------------------------------------------------------------------
ATCD = {
    "hta": (["HTA", "HTA traitée", "hypertension artérielle"], ["amlodipine 5 mg", "ramipril 5 mg", "indapamide 1,5 mg"]),
    "dt2": (["DT2", "diabète de type 2 non insulinotraité", "DT2 sous insuline"], ["metformine 1000 mg x2", "insuline glargine 18 UI"]),
    "fa": (["FA permanente sous AOD", "ACFA", "FA paroxystique"], ["apixaban 5 mg x2", "bisoprolol 2,5 mg"]),
    "ic": (["cardiopathie ischémique, FEVG 3{d} %", "insuffisance cardiaque à FEVG altérée", "IC à FEVG préservée"],
           ["furosémide 40 mg", "bisoprolol 5 mg", "sacubitril/valsartan"]),
    "coronarien": (["IDM stenté en 201{d}", "coronaropathie stentée"], ["aspirine 75 mg", "atorvastatine 40 mg"]),
    "bpco": (["BPCO GOLD 3", "BPCO sous OLD 2 L/min", "BPCO post-tabagique"], ["tiotropium", "salbutamol si besoin"]),
    "irc": (["IRC stade 3b", "insuffisance rénale chronique (DFG 3{d})"], []),
    "avc": (["AVC ischémique en 201{d} sans séquelle", "AIT en 2021"], ["clopidogrel 75 mg"]),
    "cancer": (["néo du sein en 201{d} en rémission", "adénocarcinome prostatique sous hormonothérapie",
                "cancer colique opéré en 201{d}"], []),
    "depression": (["syndrome dépressif", "dépression traitée"], ["sertraline 50 mg", "mirtazapine 15 mg"]),
    "osteoporose": (["ostéoporose fracturaire", "FESF opérée en 201{d}"], ["alendronate 70 mg/sem"]),
    "parkinson": (["maladie de Parkinson"], ["lévodopa/bensérazide"]),
    "saos": (["SAOS appareillé"], []),
    "obesite": (["obésité (IMC 3{d})"], []),
    "hypothyroidie": (["hypothyroïdie substituée"], ["lévothyroxine 75 µg"]),
}

TTT_ABSENT = ["TTT : cf ordonnance.", "TTT habituel : ordonnance non disponible.", "Traitement habituel à récupérer auprès de la pharmacie."]

# --------------------------------------------------------------------------
# Champs sociaux, cognitifs, fonctionnels (statut : documenté, négation, hypothèse)
# Chaque entrée : (texte, valeur, statut)
# --------------------------------------------------------------------------
# Situation (communes à toutes les notes d'un séjour) : les formulations sont choisies selon la
# situation tirée une fois pour le patient, jamais indépendamment les unes des autres.
LOGEMENT = {"appart_sans_ascenseur": "appartement au 2e étage sans ascenseur", "appart_ascenseur": "appartement avec ascenseur",
            "maison_plain_pied": "maison de plain-pied", "maison_etage": "maison à étage"}

PRINCIPALE = {
    # vit seul : selon le statut marital
    "seul": {"veuf": ["{Veuf}, vit seul{e}.", "{Veuf} depuis 201{d}, vit seul{e}."],
             "divorce": ["Divorcé{e}, vit seul{e}."],
             "celibataire": ["Célibataire, vit seul{e}."],
             "generique": ["Vit seul{e} à domicile.", "Vit seul{e} en {logement}.", "Vit seul{e} à dom.", "Seul{e} à domicile."]},
    # ne vit pas seul : selon le cohabitant
    "cohabite": {"conjoint": ["Vit avec {conjoint}.", "Vit en couple à domicile.", "Vit avec {conjoint} en {logement}."],
                 "enfant": ["Vit avec {enfant}.", "Vit chez {enfant}."]},
    # aidant : selon le type
    "aidant": {"conjoint": ["{Conjoint_aidant}."],
               "fille": ["Fille très présente, passe tous les jours.", "Sa fille assure l'essentiel de l'aide."],
               "fils": ["Fils à proximité, joignable.", "Son fils passe chaque soir."],
               "niece": ["Nièce référente, passe 2 fois par semaine."]},
    "aidant_absent": ["Pas d'entourage proche.", "Aucun aidant identifié.", "Famille éloignée, peu présente."],
    # aides en place : selon le type
    "aides": {"aide_menagere": ["aide ménagère 2 fois par semaine"], "ide": ["passage IDE quotidien pour les traitements"],
              "portage": ["portage des repas"], "telealarme": ["téléalarme"], "ssiad": ["SSIAD matin et soir"],
              "auxiliaire": ["auxiliaire de vie 1 h par jour"], "apa": ["APA en place"]},
    "aides_absentes": ["Pas d'aide à domicile.", "Aucune aide en place.", "Pas d'aide extérieure."],
    "cognitif_vrai": ["Troubles cognitifs connus, suivi{e} en consultation mémoire.",
                      "Maladie d'Alzheimer (MMS 1{d}/30 en 2024).", "Troubles mnésiques connus.",
                      "Démence mixte connue, désorientation ancienne selon l'entourage."],
    "cognitif_faux": ["Pas de troubles cognitifs connus.", "Pas de trouble mnésique rapporté.",
                      "Cognition préservée selon l'entourage."],
    "cognitif_hypo": ["Troubles mnésiques évoqués par l'entourage, non explorés.", "Possible syndrome démentiel débutant ?"],
    "perte_vrai": ["Perte d'autonomie progressive depuis {n} semaines, ne se lève plus seul{e}.",
                   "Chutes répétées depuis 1 mois.", "Déclin fonctionnel récent rapporté par l'entourage.",
                   "Ne fait plus ses courses depuis le mois dernier, s'est beaucoup affaibli{e}."],
    "perte_faux": ["Autonome jusqu'à l'épisode actuel.", "Pas de perte d'autonomie récente."],
    "evalsoc_vrai": ["Demande d'évaluation sociale faite.", "Assistante sociale à contacter.",
                     "Bilan social à prévoir.", "Situation sociale à évaluer, maintien à domicile difficile ?"],
    "orientation_hypo": ["Retour à domicile à discuter selon l'évolution.", "Orientation SMR à envisager.",
                         "Projet de vie à rediscuter avec la famille (EHPAD ?)."],
    # autonomie : (texte, aides techniques compatibles ; None = toutes)
    "autonomie": {1: [("Autonome pour les actes de la vie quotidienne.", None), ("Totalement autonome.", None),
                      ("Autonome, marche sans aide.", {"aucune"})],
                  2: [("Aide partielle pour la toilette.", None), ("Autonomie partielle, aide pour les courses.", None),
                      ("Aide pour la toilette du dos et les pieds.", None)],
                  3: [("Aide pour la toilette et l'habillage.", None), ("Dépendant{e} pour la toilette, aide à l'habillage.", None),
                      ("Aide pour la majorité des AVQ.", None)],
                  4: [("Dépendant{e} pour tous les actes de la vie quotidienne.", None),
                      ("Grabataire.", {"alite"}), ("Dépendance totale, alité{e}.", {"alite"})]},
    # mobilité : selon l'aide technique
    "mobilite": {"aucune": ["Marche seul{e} sans aide technique.", "Déambulation autonome."],
                 "canne": ["Marche avec une canne."], "deambulateur": ["Marche avec déambulateur."],
                 "tierce_personne": ["Déplacements avec aide d'une personne."],
                 "fauteuil": ["Ne marche plus, fauteuil roulant."],
                 "transfert_deux": ["Transferts lit-fauteuil avec aide de deux personnes."],
                 "alite": ["Alité{e}, brancard."]},
    "oxygene_vrai": ["Sous O2 {d} L/min aux lunettes.", "SpO2 8{d} % en AA, mise sous O2 2 L/min.", "O2 3 L/min, SpO2 94 %."],
    "oxygene_faux": ["SpO2 9{d} % en air ambiant.", "Pas d'oxygénothérapie."],
}

HORS_VOCABULAIRE = {
    "seul": {"veuf": ["Isolement : seul{e} au domicile depuis le décès du conjoint."],
             "divorce": ["Personne au domicile la nuit."], "celibataire": ["Personne au domicile la nuit."],
             "generique": ["Habite seul{e} dans une {logement}.", "Logement individuel, personne ne vit avec {lui}."]},
    "cohabite": {"conjoint": ["Partage son logement avec {conjoint}.", "{Conjoint_present} présent{ce} au domicile."],
                 "enfant": ["Hébergé{e} par {enfant}."]},
    "aides": {"aide_menagere": ["femme de ménage le mardi"], "portage": ["repas livrés par la mairie"],
              "ssiad": ["intervention d'une aide-soignante du SSIAD le matin"], "apa": ["plan APA : 20 h/mois"]},
    "aides_absentes": ["Aucun intervenant à domicile.", "Ne bénéficie d'aucun service à domicile."],
    "cognitif_vrai": ["MNC majeur connu (Alzheimer).", "Désorientation chronique, oublis fréquents depuis 2 ans.",
                      "Suivi neurologique pour déclin cognitif."],
    "cognitif_faux": ["Pas de plainte mnésique.", "Fonctions supérieures conservées.", "Gère seul{e} ses papiers et son pilulier."],
    "perte_vrai": ["Se déplace de moins en moins depuis quelques semaines.", "Glissement fonctionnel depuis {n} semaines.",
                   "Ne peut plus faire sa toilette seul{e} depuis peu."],
    "perte_faux": ["Faisait encore ses courses la semaine dernière.", "Autonomie conservée avant l'épisode."],
    "autonomie": {1: [("Indépendant{e} dans tous les gestes du quotidien.", None)],
                  2: [("Besoin d'un coup de main pour la douche.", None)],
                  3: [("Toilette et habillage faits par un tiers.", None)],
                  4: [("Entièrement dépendant{e}, ne quitte plus le lit.", {"alite"})]},
}

# --------------------------------------------------------------------------
# Gabarits de structure par type de note
# --------------------------------------------------------------------------
ENTETES = {
    "OBS_URGENCES": ["OBSERVATION URGENCES", "Observation médicale - SAU", "URGENCES - Observation"],
    "OBS_ENTREE": ["OBSERVATION D'ENTRÉE - {service}", "Observation médicale d'entrée ({service})", "{service} - Entrée"],
    "RECUEIL_IDE": ["RECUEIL DE DONNÉES IDE - ENTRÉE", "Recueil infirmier d'accueil", "Accueil IDE"],
}
CAT_URG = ["CAT : hospitalisation en {service}.", "Hospitalisation en {service}, lit demandé.",
           "Avis {service} : accepte, hospitalisation.", "Décision d'hospitalisation en {service}."]
HEBERGE = ["Patient{e} hébergé{e} en {hote}, relève de {service}.", "Hébergement en {hote} faute de lit en {service}."]
COMPLEMENTS = ["Complément", "Ajout", "Complément d'observation", "Mise à jour"]
CONTACT_FAMILLE = {
    "conjoint": ["Échange avec {conjoint} :"], "fille": ["Contact téléphonique avec la fille :"],
    "fils": ["Appel du fils :"], "niece": ["Entretien avec la nièce :"],
    "aucun": ["Information recueillie auprès du voisin :", "Appel du médecin traitant :"],
}
SOURCE_ANCIENNE = ["(cf. CRH 2023)", "(cf. observation précédente)", "(données dossier 2022)"]
ABREVIATIONS = [("patient", "pt"), ("domicile", "dom"), ("avec", "av"), ("antécédents", "ATCD"),
                ("traitement", "TTT"), ("examen", "ex"), ("jours", "j"), ("semaines", "sem")]
