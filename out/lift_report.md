# Lift: cold start vs context file

Same 6 synthetic users (3 buyers, 3 sellers), same scripted answers. Deterministic policy, template replies.

| Metric | Cold start | With context | Change |
|---|---|---|---|
| Re-asks of facts already known | 18 | **0** | -100% |
| Questions asked | 30 | **13** | -57% |
| User turns to goal | 36 | **13** | -64% |
| Est. voice time (~9 s/turn) | 378 s | **171 s** | -55% |
| Goal reached (buyer transfer / seller lead follow-up) | 3/6 | **6/6** | |
| Personalised openings | 0/6 | **6/6** | |

## Openings

| GLID | Cold start | From context file | Facts used |
|---|---|---|---|
| 50112001 (buyer) | Namaste, IndiaMART se Vani bol rahi hoon. Kya aap PVC Pipe ke liye dekh rahe hain, jo plumbing aur paani ki supply line ke kaam aata hai? | Namaste Ramesh ji, IndiaMART se Vani bol rahi hoon. Kal aapne WhatsApp par 500 piece, 4 inch PVC Pipe ki requirement batayi thi. Bas ek baat, Pressure Rating mein kya chahiye, 4 kg ya 6 kg, ya kuch aur? | 7 |
| 50112002 (buyer) | Namaste, IndiaMART se Vani bol rahi hoon. Kya aap Industrial RO Plant ke liye dekh rahe hain, jo factory aur commercial jagah par paani saaf karne ke kaam aata hai? | Hello Lakshmi, this is Vani from IndiaMART. Our call 3 days ago got cut while we were noting your 1 unit, 2000 litre per hour Industrial RO Plant requirement. Just one thing: which body material do you need, SS 304 or FRP, or something else? | 7 |
| 50112003 (buyer) | Namaste, IndiaMART se Vani bol rahi hoon. Bataiye, aaj aapko kis product ki requirement hai? | Namaste Arjun ji, IndiaMART se Vani bol rahi hoon. Kya aap Bubble Wrap Roll ke liye dekh rahe hain, jo packing mein saamaan ko toot-phoot se bachata hai? | 2 |
| 70221001 (seller) | Namaste, IndiaMART se Vani bol rahi hoon. Main aapki kya madad kar sakti hoon? | Namaste Sunil ji, IndiaMART se Vani bol rahi hoon. Kal aapko Indore se 500 Piece 4 inch PVC Pipe ki lead mili thi aur us buyer ki call bhi aapse miss ho gayi thi. Kya aapki unse baat ho payi? | 6 |
| 70221002 (seller) | Namaste, IndiaMART se Vani bol rahi hoon. Main aapki kya madad kar sakti hoon? | Namaste Hetal ji, IndiaMART se Vani bol rahi hoon. Aaj aapko Ahmedabad se 200 Roll 1 meter Bubble Wrap Roll ki lead mili thi. Kya aapki unse baat ho payi? | 5 |
| 70221003 (seller) | Namaste, IndiaMART se Vani bol rahi hoon. Main aapki kya madad kar sakti hoon? | Hello Kiran, this is Vani from IndiaMART. I know you're busy right now, so just one quick thing. 3 days ago you got a lead from Hyderabad for 1 Unit 2000 litre per hour Industrial RO Plant, and their call to you was missed. Were you able to speak to the buyer? | 7 |
