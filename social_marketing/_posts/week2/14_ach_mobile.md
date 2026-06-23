# Post 14 — Jul 25

**Platform:** X (single post)  
**Title:** ACH + Mobile Money  
**Status:** Draft

---

## Post Content

Both ACH and Mobile Money adapters done.

LocalACHAdapter covers Jamaica (JMD, 1h, 15bps), Barbados (BBD, 2h, 20bps), Trinidad (TTD, 3h, 25bps), and ECCB (XCD, 30min, 10bps). Each jurisdiction's RTGS, abstracted behind one interface.

MobileMoneyAdapter covers MonCash (Haiti), e-cash (Jamaica), mMoney (Barbados). 10 second settlement, higher fees, lower barrier.

Three rails. One interface. Best path wins.

#CARIB_CLEAR #FutureCaribbean #Buildathon

---

## Review Notes
- [ ] Good details on the different rails?
- [ ] Clear why three matter?