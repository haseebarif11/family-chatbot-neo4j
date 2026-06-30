% Family knowledge base — facts and derived relationship rules
% Facts below are the canonical seed data (14 people). Runtime updates go to Neo4j via data_entry.

% --- Facts ---

% parent(Parent, Child)
parent(haider, ali).
parent(haider, sara).
parent(nadia, ali).
parent(nadia, sara).
parent(ali, laiba).
parent(ali, usman).
parent(zara, laiba).
parent(zara, usman).
parent(kamran, haider).
parent(rukhsana, haider).
parent(kamran, hina).
parent(rukhsana, hina).
parent(kamran, zara).
parent(rukhsana, zara).
parent(hina, lina).
parent(kamran, sohail).
parent(rukhsana, sohail).
parent(hina, ahmed).
parent(sohail, ahmed).

% male(Person)
male(ahmed).
male(haider).
male(ali).
male(usman).
male(kamran).
male(sohail).

% female(Person)
female(nadia).
female(sara).
female(laiba).
female(zara).
female(rukhsana).
female(hina).
female(lina).
female(sarah).

% married(Husband, Wife) — one direction per couple; migration deduplicates
married(haider, nadia).
married(ali, zara).
married(kamran, rukhsana).
married(sohail, sarah).

% age(Person, Years)
age(kamran, 75).
age(rukhsana, 70).
age(haider, 50).
age(nadia, 48).
age(hina, 45).
age(ali, 28).
age(zara, 26).
age(sara, 24).
age(laiba, 5).
age(usman, 3).
age(sohail, 40).
age(ahmed, 30).
age(lina, 2).
age(sarah, 30).

% dob(Person, Date)
dob(kamran,    '1950-04-10').
dob(rukhsana,  '1955-08-22').
dob(haider,    '1975-06-15').
dob(nadia,     '1977-11-03').
dob(hina,      '1980-02-28').
dob(ali,       '1997-03-14').
dob(zara,      '1999-07-19').
dob(sara,      '2001-09-05').
dob(laiba,     '2020-01-11').
dob(usman,     '2022-05-30').
dob(lina,      '2024-06-15').
dob(sarah,     '1996-04-01').

% --- Derived rules (reference; runtime reasoning is in Neo4j/Cypher) ---

father(X, Y)              :- parent(X, Y), male(X).
mother(X, Y)              :- parent(X, Y), female(X).
grandfather(X, Y)         :- father(X, Z), parent(Z, Y).
grandmother(X, Y)         :- mother(X, Z), parent(Z, Y).
grandparent(X, Y)         :- parent(X, Z), parent(Z, Y).
sibling(X, Y)             :- parent(Z, X), parent(Z, Y), X \= Y.
brother(X, Y)             :- sibling(X, Y), male(X).
sister(X, Y)              :- sibling(X, Y), female(X).
son(X, Y)                 :- parent(Y, X), male(X).
daughter(X, Y)            :- parent(Y, X), female(X).
uncle(X, Y)               :- brother(X, Z), parent(Z, Y).
aunt(X, Y)                :- sister(X, Z), parent(Z, Y).
cousin(X, Y)              :- parent(A, X), parent(B, Y), sibling(A, B).
nephew(X, Y)              :- sibling(Y, Z), son(X, Z).
niece(X, Y)               :- sibling(Y, Z), daughter(X, Z).
ancestor(X, Y)            :- parent(X, Y).
ancestor(X, Y)            :- parent(X, Z), ancestor(Z, Y).
descendant(X, Y)          :- ancestor(Y, X).
husband(X, Y)             :- married(X, Y).
wife(X, Y)                :- married(Y, X).
spouse(X, Y)              :- married(X, Y).
spouse(X, Y)              :- married(Y, X).
father_in_law(X, Y)       :- spouse(Y, Z), father(X, Z).
mother_in_law(X, Y)       :- spouse(Y, Z), mother(X, Z).
brother_in_law(X, Y)      :- spouse(Y, Z), brother(X, Z).
sister_in_law(X, Y)       :- spouse(Y, Z), sister(X, Z).
is_elder(X, Y)            :- age(X, AX), age(Y, AY), AX > AY.
is_younger(X, Y)          :- age(X, AX), age(Y, AY), AX < AY.
elder_sibling(X, Y)       :- sibling(X, Y), is_elder(X, Y).
younger_sibling(X, Y)     :- sibling(X, Y), is_younger(X, Y).
paternal_grandfather(X, Y) :- father(Z, Y), father(X, Z).
same_generation(X, Y) :- sibling(X, Y).
same_generation(X, Y) :- spouse(X, Y).
same_generation(X, Y) :- parent(PX, X), parent(PY, Y), same_generation(PX, PY), X \= Y.
