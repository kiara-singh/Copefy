"""Synthetic journal dataset seeder.

Populates 100 realistic, diverse synthetic journal entries for testing journal RAG retrieval.
Inserts into source journal_entries and runs them through the REAL ingestion path (gemini-embedding-2).
Idempotent: Re-running this script will NOT duplicate journal entries.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from db import get_pool
from rag.journal_ingestion import ingest_journal_entry_asyncpg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DUMMY_JOURNAL_ENTRIES = [
    # 1. Exam Anxiety Series (Recurring)
    {
        "content": (
            "I am feeling so anxious about my upcoming midterm exam in organic chemistry. "
            "I've been studying for hours every night, but my mind keeps racing and I keep worrying "
            "that I will freeze up when I see the test paper."
        ),
        "created_at": "2026-03-10T10:00:00Z",
    },
    {
        "content": (
            "Studied for four hours at the library today for the chemistry exam. Tried doing practice "
            "problems instead of just re-reading notes. Felt a bit more in control, but my chest still "
            "tightens whenever I think about the countdown."
        ),
        "created_at": "2026-03-12T18:30:00Z",
    },
    {
        "content": (
            "Got my chemistry exam results back today. I ended up getting an B+, which was much better "
            "than I feared. All that severe exam anxiety beforehand was worse than the test itself."
        ),
        "created_at": "2026-03-18T15:20:00Z",
    },
    {
        "content": (
            "Now I have a calculus final approaching in two weeks and that familiar knot in my stomach "
            "is returning. It feels like as soon as one test ends, another wave of exam panic starts."
        ),
        "created_at": "2026-04-14T11:00:00Z",
    },
    {
        "content": (
            "Tried studying late into the night with three energy drinks for my calculus test. "
            "Big mistake. It didn't help my comprehension at all and just left me jittery and panicked."
        ),
        "created_at": "2026-04-18T02:30:00Z",
    },
    {
        "content": (
            "Made study flashcards with colorful headers for biology. Breaking the material into tiny "
            "manageable chunks actually kept my exam anxiety down today."
        ),
        "created_at": "2026-05-08T16:15:00Z",
    },
    {
        "content": (
            "Helped my roommate review their biology flashcards before their exam. It was nice to be "
            "in the helper role for once without feeling personal test stress."
        ),
        "created_at": "2026-05-10T20:00:00Z",
    },
    {
        "content": (
            "Finals week is officially starting tomorrow. I felt overwhelmed this morning, but I organized "
            "my study schedule and told myself that one test does not define my entire worth."
        ),
        "created_at": "2026-06-01T09:00:00Z",
    },

    # 2. Public Speaking & Presentations (Recurring)
    {
        "content": (
            "Had to give a presentation in my seminar class today. Public speaking always makes me "
            "so nervous. My hands were shaking and my heart was pounding before I stepped up to the front. "
            "I survived, but I hated feeling that loss of control."
        ),
        "created_at": "2026-03-14T14:30:00Z",
    },
    {
        "content": (
            "Professor announced that our group project requires a 20-minute presentation at the end of the term. "
            "Just hearing the word presentation made my stomach drop."
        ),
        "created_at": "2026-03-22T13:10:00Z",
    },
    {
        "content": (
            "Practiced my presentation slides in front of my mirror three times tonight. "
            "Speaking the words out loud helped reduce the stuttering, but public speaking still terrifies me."
        ),
        "created_at": "2026-04-05T20:45:00Z",
    },
    {
        "content": (
            "Gave the group presentation this morning. I volunteered to do the introductory slides so I could "
            "get my part over with early. It actually went smoothly and no one noticed my hands trembling."
        ),
        "created_at": "2026-04-08T16:00:00Z",
    },
    {
        "content": (
            "Walked past the main lecture auditorium while another department was having a student symposium. "
            "Felt glad I didn't have to present today."
        ),
        "created_at": "2026-05-15T12:30:00Z",
    },
    {
        "content": (
            "Had to introduce myself in a new workshop circle today. Even speaking to ten people in a circle "
            "triggered that presentation anxiety feeling. Need to work on breathing through it."
        ),
        "created_at": "2026-07-12T10:15:00Z",
    },

    # 3. Sleep & Insomnia vs. Sleep Hygiene (Recurring)
    {
        "content": (
            "Couldn't fall asleep until past 3am last night. My mind just wouldn't turn off. "
            "I kept thinking about all the deadlines coming up next week and how little time I have. "
            "Woke up feeling completely exhausted."
        ),
        "created_at": "2026-03-05T08:15:00Z",
    },
    {
        "content": (
            "Tried putting my phone in another room an hour before bed like I planned. "
            "Fell asleep much faster around 11:30pm and woke up feeling significantly more rested."
        ),
        "created_at": "2026-03-08T07:45:00Z",
    },
    {
        "content": (
            "Another night of staring at the ceiling. Woke up at 2am and couldn't get back to sleep for "
            "two hours. My sleep schedule is completely wrecked this week."
        ),
        "created_at": "2026-03-25T07:00:00Z",
    },
    {
        "content": (
            "Drank chamomile tea and read a paperback novel before turning off the lights. "
            "It seemed to help quiet the mental chatter and I slept seven solid hours."
        ),
        "created_at": "2026-03-28T08:00:00Z",
    },
    {
        "content": (
            "Stayed up watching video essays until 4am because I was procrastinating on an essay. "
            "Now I have a splitting headache and feel like a zombie."
        ),
        "created_at": "2026-04-20T10:30:00Z",
    },
    {
        "content": (
            "Set a strict 11pm bedtime alarm all week. My body is slowly adjusting. "
            "Having a consistent wake-up time is definitely making the biggest difference."
        ),
        "created_at": "2026-05-02T07:15:00Z",
    },
    {
        "content": (
            "Loud sirens outside woke me up at 3am and I couldn't fall back asleep. "
            "Tossed and turned thinking about past arguments with friends."
        ),
        "created_at": "2026-06-18T06:45:00Z",
    },
    {
        "content": (
            "I was completely exhausted today after helping my cousin move furniture for five hours. "
            "Fell straight to sleep the moment my head touched the pillow."
        ),
        "created_at": "2026-07-22T22:00:00Z",
    },
    {
        "content": (
            "Tried taking a warm shower before bed to relax my tight shoulders. "
            "It helped physically, but my thoughts still kept racing about job applications."
        ),
        "created_at": "2026-08-04T23:30:00Z",
    },

    # 4. Roommate Conflict & Living Situation (Recurring)
    {
        "content": (
            "My roommate left a pile of dirty dishes in the sink again for the third day in a row. "
            "I tried talking to them nicely, but they brushed it off. It's frustrating because I like "
            "having a clean living space to stay relaxed."
        ),
        "created_at": "2026-03-16T19:00:00Z",
    },
    {
        "content": (
            "Had an honest conversation with my roommate about dividing household chores. "
            "We agreed to take turns taking out the trash and keeping common counters wiped down. "
            "Relieved that we spoke without turning it into a fight."
        ),
        "created_at": "2026-03-20T21:15:00Z",
    },
    {
        "content": (
            "Roommate had friends over late on a Tuesday night without giving me a heads up. "
            "I had an 8am class the next day and couldn't sleep with all the laughing in the living room."
        ),
        "created_at": "2026-04-12T01:30:00Z",
    },
    {
        "content": (
            "Cooked dinner together with my roommate tonight. Made pasta and chatted about our hometowns. "
            "It was a nice reminder that despite small living friction, they are actually a decent person."
        ),
        "created_at": "2026-05-20T20:00:00Z",
    },
    {
        "content": (
            "Roommate borrowed my headphones without asking and left them on the kitchen table. "
            "Need to set clearer boundaries around personal belongings."
        ),
        "created_at": "2026-06-25T18:40:00Z",
    },
    {
        "content": (
            "Met my new potential roommate for next semester over coffee. She seems super quiet and tidy. "
            "Hoping the transition goes smoothly."
        ),
        "created_at": "2026-07-30T15:00:00Z",
    },

    # 5. Homesickness & Family Relationships (Recurring)
    {
        "content": (
            "Feeling really homesick today. Called my family for an hour this evening. "
            "It's hard being far away from home during stressful weeks at school."
        ),
        "created_at": "2026-03-02T21:00:00Z",
    },
    {
        "content": (
            "Received a care package from my mom with homemade cookies and cozy socks. "
            "I literally teared up opening it. Missing home so much this week."
        ),
        "created_at": "2026-03-24T17:00:00Z",
    },
    {
        "content": (
            "Got into a small argument with my dad over my summer plans. He wants me to come home immediately, "
            "but I want to do an internship on campus. Feeling torn between independence and family."
        ),
        "created_at": "2026-04-28T19:30:00Z",
    },
    {
        "content": (
            "Visited home for the long weekend. It was comforting to sleep in my old childhood bedroom, "
            "though it felt strange seeing how much my hometown has changed."
        ),
        "created_at": "2026-05-25T21:45:00Z",
    },
    {
        "content": (
            "FaceTimed my little brother to help him with his algebra homework. "
            "Hearing him laugh made me feel much more connected to home."
        ),
        "created_at": "2026-07-15T18:00:00Z",
    },

    # 6. Overwhelm, Workload & Procrastination (Recurring)
    {
        "content": (
            "Feeling completely overwhelmed with schoolwork right now. I have three major assignments "
            "and a lab report all due on Friday. I don't even know where to start organizing my time."
        ),
        "created_at": "2026-03-11T16:00:00Z",
    },
    {
        "content": (
            "Spent the entire afternoon scrolling on social media instead of writing my history paper. "
            "The guilt of procrastinating is almost worse than the task itself."
        ),
        "created_at": "2026-03-30T18:20:00Z",
    },
    {
        "content": (
            "Tried using the Pomodoro technique today — 25 minutes of focused writing, 5 minutes break. "
            "Actually finished two full pages of my essay! Breaking the inertia is the hardest part."
        ),
        "created_at": "2026-04-02T16:45:00Z",
    },
    {
        "content": (
            "My calendar is packed with back-to-back commitments between classes, labs, and group meetings. "
            "I feel like I'm running on a treadmill that's going just a little too fast."
        ),
        "created_at": "2026-04-22T17:15:00Z",
    },
    {
        "content": (
            "Wrote a priority matrix on my whiteboard: urgent vs important. "
            "Crossing off the top two tasks gave me a huge sense of relief."
        ),
        "created_at": "2026-05-04T19:00:00Z",
    },
    {
        "content": (
            "Struggled with brain fog all morning. Could barely read through research papers without "
            "zoning out. Ended up taking a nap instead of forcing it."
        ),
        "created_at": "2026-06-12T14:00:00Z",
    },
    {
        "content": (
            "Submitted my final paper 10 minutes before the midnight deadline. "
            "The rush of adrenaline was intense, but I swore to myself I won't cut it that close again."
        ),
        "created_at": "2026-06-20T23:55:00Z",
    },

    # 7. Exercise & Outdoor Activity (Recurring)
    {
        "content": (
            "Decided to force myself to go for a 30-minute run in the morning despite feeling down. "
            "Surprisingly, exercise actually helped boost my mood and clear my head for the rest of the day. "
            "I need to remember how good this felt."
        ),
        "created_at": "2026-03-13T09:30:00Z",
    },
    {
        "content": (
            "Went for a walk around the neighborhood in the drizzle hoping it would cheer me up. "
            "It was cold and wet, and I just came back feeling soggy and annoyed rather than refreshed."
        ),
        "created_at": "2026-03-29T16:00:00Z",
    },
    {
        "content": (
            "Went to the campus gym for the first time in months. Felt self-conscious about people looking at me, "
            "so I stayed on the treadmill in the corner. Glad I went anyway."
        ),
        "created_at": "2026-04-10T17:30:00Z",
    },
    {
        "content": (
            "Rode my bicycle along the river trail on a sunny Saturday afternoon. "
            "The fresh breeze and movement genuinely helped lift the heavy mood I had all week."
        ),
        "created_at": "2026-05-16T15:30:00Z",
    },
    {
        "content": (
            "Did a 20-minute beginner yoga session in my room following a video. "
            "My hamstrings are super tight, but stretching out the tension in my back felt amazing."
        ),
        "created_at": "2026-06-28T08:30:00Z",
    },
    {
        "content": (
            "Went for a brisk morning walk with a podcast. Getting sunlight in my eyes early in the morning "
            "seems to wake my brain up much better than just chugging coffee."
        ),
        "created_at": "2026-08-10T08:00:00Z",
    },

    # 8. Coping Techniques, Breathing & Mindfulness (Recurring)
    {
        "content": (
            "Tried the box breathing technique my counselor suggested right before my group meeting today. "
            "Inhaled for 4, held for 4, exhaled for 4. It genuinely helped settle my nervous energy and "
            "kept my heart rate down."
        ),
        "created_at": "2026-03-15T11:45:00Z",
    },
    {
        "content": (
            "Tried doing the 5-4-3-2-1 grounding technique when I felt a panic spike in the dining hall. "
            "5 things I see, 4 things I feel, 3 things I hear... It pulled my brain out of the spiral "
            "and brought me back to reality."
        ),
        "created_at": "2026-04-06T12:45:00Z",
    },
    {
        "content": (
            "Downloaded a guided meditation app and tried a 10-minute session. "
            "I found it really frustrating because the narrator kept telling me to clear my mind, "
            "which just made me think about all my worries even more."
        ),
        "created_at": "2026-04-16T22:15:00Z",
    },
    {
        "content": (
            "When anxiety flared up during study session, I held an ice cube in my palm for 60 seconds. "
            "The cold sensation shocked my nervous system and stopped the racing thoughts instantly."
        ),
        "created_at": "2026-05-22T14:10:00Z",
    },
    {
        "content": (
            "Practiced progressive muscle relaxation before bed. Tensing and releasing my feet, calves, "
            "and shoulders helped me realize how much physical tension I hold unconsciously."
        ),
        "created_at": "2026-07-08T23:00:00Z",
    },

    # 9. Friendships, Socializing & Social Anxiety (Recurring)
    {
        "content": (
            "Went to a club social mixer. Spent the first twenty minutes hovering near the snack table "
            "wondering if I should just leave. Ended up chatting with someone who also likes sci-fi novels. "
            "Proud of myself for not running away."
        ),
        "created_at": "2026-03-19T20:30:00Z",
    },
    {
        "content": (
            "Felt left out when I saw photos of a group of classmates getting boba together without inviting me. "
            "Trying not to take it personally, but rejection sensitivity is hard to silence."
        ),
        "created_at": "2026-04-15T18:15:00Z",
    },
    {
        "content": (
            "Had coffee with Maya from my chemistry lab. We talked for nearly two hours about music, "
            "classes, and how stressful college can be. It felt so good to have a genuine conversation."
        ),
        "created_at": "2026-04-26T16:00:00Z",
    },
    {
        "content": (
            "Canceled dinner plans with friends tonight because I felt socially drained and anxious. "
            "Now I feel guilty for flaking, even though I really needed alone time."
        ),
        "created_at": "2026-05-30T19:00:00Z",
    },
    {
        "content": (
            "Hosted a small board game night in our dorm lounge with three friends. "
            "Low-pressure social settings are so much easier for me than noisy parties."
        ),
        "created_at": "2026-06-15T21:00:00Z",
    },
    {
        "content": (
            "Ran into an old high school acquaintance on campus. It was a brief and pleasant chat, "
            "and I didn't overthink it for hours afterward like I used to."
        ),
        "created_at": "2026-07-25T13:45:00Z",
    },

    # 10. Low Energy, Depression & Mood Fluctuations (Recurring)
    {
        "content": (
            "Woke up with zero motivation today. Everything felt like moving through wet cement. "
            "Managed to shower and eat a piece of toast, which felt like a victory."
        ),
        "created_at": "2026-03-27T12:00:00Z",
    },
    {
        "content": (
            "The gray, rainy weather all week is really dragging my mood down. "
            "Sitting by the window with a warm lamp helped a little bit."
        ),
        "created_at": "2026-04-04T15:30:00Z",
    },
    {
        "content": (
            "Felt a strange sense of emptiness today, like I'm watching my life from behind a glass wall. "
            "I couldn't pinpoint any specific trigger."
        ),
        "created_at": "2026-05-18T20:10:00Z",
    },
    {
        "content": (
            "Had a genuinely good mood day today! Finished my chores early, listened to my favorite album, "
            "and felt optimistic about the future for the first time in a while."
        ),
        "created_at": "2026-06-08T17:40:00Z",
    },
    {
        "content": (
            "Felt a dip in energy again this afternoon. Reminded myself that healing isn't linear "
            "and bad days don't erase the progress I've made."
        ),
        "created_at": "2026-07-18T16:20:00Z",
    },

    # 11. Academic Successes & Failures (Recurring)
    {
        "content": (
            "Received my midterm essay back in English literature with an A- and positive instructor feedback. "
            "My analysis of Victorian symbolism was praised. It feels validating when hard work pays off."
        ),
        "created_at": "2026-03-23T14:00:00Z",
    },
    {
        "content": (
            "Failed a pop quiz in statistics today. I got 4 out of 10. "
            "I spiraled for an hour thinking I'm not cut out for this major, but I need to talk to the TA."
        ),
        "created_at": "2026-04-09T16:30:00Z",
    },
    {
        "content": (
            "Attended statistics office hours this afternoon. The TA explained probability distributions "
            "with clear visual examples. I understand the formulas much better now."
        ),
        "created_at": "2026-04-17T15:00:00Z",
    },
    {
        "content": (
            "Passed my statistics retake quiz with an 85%! "
            "Seeking help early actually saved me from failing the unit."
        ),
        "created_at": "2026-04-24T17:00:00Z",
    },

    # 12. Work, Career & Internship Search (Recurring)
    {
        "content": (
            "Submitted four summer internship applications today. Tailoring each cover letter took hours. "
            "Hoping I hear back from at least one company."
        ),
        "created_at": "2026-03-31T22:00:00Z",
    },
    {
        "content": (
            "Received an automated rejection email from the research lab I applied to. "
            "Stings a bit, but I know it's a numbers game."
        ),
        "created_at": "2026-04-21T11:20:00Z",
    },
    {
        "content": (
            "Got an invitation for a 30-minute virtual interview next Tuesday! "
            "Excited, but already feeling the nervous butterflies in my stomach."
        ),
        "created_at": "2026-05-06T14:30:00Z",
    },
    {
        "content": (
            "Completed the interview. Stumbled a bit on the 'tell me about a challenge' question, "
            "but I recovered and spoke clearly about my project experience."
        ),
        "created_at": "2026-05-12T16:45:00Z",
    },
    {
        "content": (
            "They offered me the summer internship! The stipend is fair and I get to work with real data. "
            "All the anxiety over the past two months was worth it."
        ),
        "created_at": "2026-05-19T17:15:00Z",
    },
    {
        "content": (
            "First week of my internship completed. Imposter syndrome was high on Monday, but my mentor "
            "is patient and encouraged me to ask questions whenever I get stuck."
        ),
        "created_at": "2026-06-26T18:00:00Z",
    },

    # 13. Multi-Paragraph Entries (Testing Structure-Aware Chunker)
    {
        "content": (
            "Today was an intense rollercoaster of emotions. In the morning, I woke up feeling anxious "
            "because my statistics project was due at noon and my code had an unexpected bug.\n\n"
            "I spent two hours debugging with my lab partner in the computer lab. We finally found a missing "
            "parenthesis at 11:30am and submitted right on time. The relief was overwhelming.\n\n"
            "After class, I rewarded myself by sitting in the campus botanical garden with an iced tea. "
            "Taking time to decompress after high-stress spikes is something I need to make a regular habit."
        ),
        "created_at": "2026-04-03T17:30:00Z",
    },
    {
        "content": (
            "Reflecting on how my coping habits have evolved over the last semester. At the beginning of the "
            "year, whenever anxiety hit, I would isolate in my dorm room for days and avoid answering texts.\n\n"
            "Now, I've developed a small toolkit: box breathing when my chest feels tight, going for a brisk run "
            "when my mind is scattered, and talking things through with Maya or my counselor instead of bottling it up.\n\n"
            "I still have tough days where everything feels overwhelming, but I don't feel completely helpless anymore."
        ),
        "created_at": "2026-06-10T20:15:00Z",
    },
    {
        "content": (
            "Had an argument with my sister over the phone about family vacation logistics. We both raised our voices "
            "and I ended up hanging up in anger.\n\n"
            "Took thirty minutes to do some deep breathing and cool down before texting her an apology for snapping. "
            "She apologized too and we managed to find a flight schedule that works for both of us."
        ),
        "created_at": "2026-07-02T19:40:00Z",
    },
    {
        "content": (
            "Spent the entire Saturday doing a deep clean of my apartment. Scrubbed the kitchen counters, vacuumed the rug, "
            "washed all my bedsheets, and organized my desk drawers.\n\n"
            "Having a clean, decluttered physical space makes an immediate difference to my mental clarity. "
            "My anxiety levels dropped significantly just seeing clear surfaces."
        ),
        "created_at": "2026-07-20T17:00:00Z",
    },

    # 14. Negative / Neighboring Semantic Variations
    {
        "content": (
            "Watched a movie with my roommate where the main character was studying for medical school. "
            "It was funny seeing how exaggerated the fictional exams were compared to real life."
        ),
        "created_at": "2026-04-11T22:00:00Z",
    },
    {
        "content": (
            "Read an article online about sleep research and circadian rhythms. Interesting to learn that "
            "teenagers naturally have later sleep cycles."
        ),
        "created_at": "2026-05-01T14:20:00Z",
    },
    {
        "content": (
            "Brought my lunch to the park bench and watched dogs playing in the grass. "
            "A peaceful, ordinary Wednesday afternoon."
        ),
        "created_at": "2026-06-03T13:00:00Z",
    },
    {
        "content": (
            "Went shopping for groceries and bought fresh strawberries and sourdough bread. "
            "Cooking simple meals from scratch has become a grounding hobby."
        ),
        "created_at": "2026-06-22T18:15:00Z",
    },
    {
        "content": (
            "Wrote down my goals for the upcoming semester in my planner: keep up with weekly readings, "
            "exercise three times a week, and maintain regular sleep hours."
        ),
        "created_at": "2026-08-15T19:30:00Z",
    },
    {
        "content": (
            "Helped a classmate find the lecture hall for their chemistry discussion section. "
            "Campus is so large it's easy for new students to get turned around."
        ),
        "created_at": "2026-08-20T10:45:00Z",
    },
    {
        "content": (
            "Bought a potted succulent for my desk windowsill. Giving it water and seeing a tiny bit of greenery "
            "adds a calm touch to my study space."
        ),
        "created_at": "2026-08-24T16:10:00Z",
    },
    {
        "content": (
            "Looking back on this summer journal, I've had ups and downs with sleep, exams, and roommate stress. "
            "Overall, I'm learning to recognize when I need to pause, breathe, and ask for support."
        ),
        "created_at": "2026-08-28T21:00:00Z",
    },

    # Additional diverse entries to complete the 100-entry dataset
    {
        "content": "Lost my student ID card today and panicked for twenty minutes before finding it in my jacket pocket.",
        "created_at": "2026-03-07T14:20:00Z",
    },
    {
        "content": "Had a great conversation with my academic advisor about course prerequisites for senior year.",
        "created_at": "2026-03-17T11:00:00Z",
    },
    {
        "content": "Listened to lo-fi beats while studying for my psychology quiz. The instrumental music helped block out dorm noise.",
        "created_at": "2026-03-21T16:30:00Z",
    },
    {
        "content": "Bought earplugs to block out the street noise at night. Slept through the night without waking up once.",
        "created_at": "2026-03-26T07:30:00Z",
    },
    {
        "content": "Felt overwhelmed by the long queue at the financial aid office. Practiced deep belly breathing while waiting.",
        "created_at": "2026-04-01T10:15:00Z",
    },
    {
        "content": "Cooked a large batch of vegetable soup and froze portions for busy exam weeks.",
        "created_at": "2026-04-07T19:45:00Z",
    },
    {
        "content": "Felt a sudden wave of panic during a crowded bus ride. Focused on counting blue cars outside the window to stay grounded.",
        "created_at": "2026-04-13T17:50:00Z",
    },
    {
        "content": "Had lunch outdoors on the campus lawn. Sunlight and fresh air helped shake off morning sluggishness.",
        "created_at": "2026-04-19T13:15:00Z",
    },
    {
        "content": "Tried studying at a new coffee shop downtown. It was too loud and crowded to concentrate, so I went back to the library.",
        "created_at": "2026-04-23T15:40:00Z",
    },
    {
        "content": "Felt proud of sticking to my weekly workout schedule for three weeks in a row.",
        "created_at": "2026-04-27T18:00:00Z",
    },
    {
        "content": "Had a small disagreement with Maya about who was presenting which section of our poster. We resolved it calmly after class.",
        "created_at": "2026-05-03T16:20:00Z",
    },
    {
        "content": "Woke up with tight jaw muscles from grinding teeth in my sleep due to finals stress.",
        "created_at": "2026-05-07T07:10:00Z",
    },
    {
        "content": "Finished my last spring final exam! Handed in the test booklet and felt 50 pounds lighter.",
        "created_at": "2026-05-14T12:00:00Z",
    },
    {
        "content": "Celebrated the end of semester with pizza and movie night with dorm friends.",
        "created_at": "2026-05-14T20:30:00Z",
    },
    {
        "content": "Started reading a fantasy novel just for fun, with no academic pressure attached.",
        "created_at": "2026-05-23T21:15:00Z",
    },
    {
        "content": "Had a quiet, reflective Sunday afternoon organizing digital photo albums from high school.",
        "created_at": "2026-05-28T16:00:00Z",
    },
    {
        "content": "Felt a little anxious about starting the new internship on Monday. Prepared my outfit and bag the night before.",
        "created_at": "2026-06-07T21:40:00Z",
    },
    {
        "content": "Successfully pushed my first code commit at the internship after code review. Team was very welcoming.",
        "created_at": "2026-06-16T17:30:00Z",
    },
    {
        "content": "Drank too much coffee during afternoon meetings and felt my heart racing. Switched to herbal tea for the rest of the day.",
        "created_at": "2026-06-24T15:10:00Z",
    },
    {
        "content": "Took a 15-minute mindful walk around the office courtyard during lunch break.",
        "created_at": "2026-07-06T12:30:00Z",
    },
    {
        "content": "Felt frustrated with a difficult software bug at work. Stepped away from the screen for twenty minutes, and the solution came to me.",
        "created_at": "2026-07-10T16:15:00Z",
    },
    {
        "content": "Had a video call with my grandmother on her birthday. She reminded me to drink water and get plenty of rest.",
        "created_at": "2026-07-14T19:00:00Z",
    },
    {
        "content": "Tried a 10-minute guided sleep meditation. The soothing ambient rain sounds helped me drift off peacefully.",
        "created_at": "2026-07-28T23:15:00Z",
    },
    {
        "content": "Signed up for a 5k fun run in September. Having a tangible fitness goal is motivating me to run regularly.",
        "created_at": "2026-08-02T10:00:00Z",
    },
    {
        "content": "Spent the afternoon volunteering at the local animal shelter walking rescue dogs. Animals have such a calming effect on my anxiety.",
        "created_at": "2026-08-08T15:30:00Z",
    },
    {
        "content": "Organized my fall course textbooks and syllabi. Ready to start the new academic year with positive momentum.",
        "created_at": "2026-08-22T14:00:00Z",
    },
    {
        "content": "Had dinner with my roommate to celebrate our final week of summer. We talked about how much we both grew over the past year.",
        "created_at": "2026-08-26T19:30:00Z",
    },
]


async def seed_synthetic_journals(user_id: str | None = None) -> tuple[str, list[str]]:
    """Seed synthetic journal entries into journal_entries and run real ingestion pipeline.

    Idempotent: Checks for existing normalized entries to prevent duplicate rows.
    """
    pool = await get_pool()
    created_entry_ids: list[str] = []

    async with pool.acquire() as conn:
        target_user_id = user_id
        if not target_user_id:
            row = await conn.fetchrow("SELECT id FROM profiles LIMIT 1")
            if row:
                target_user_id = str(row["id"])

        if not target_user_id:
            from config import settings

            target_user_id = (
                settings.seed_user_id or settings.journal_eval_user_id or ""
            ).strip() or None

        if not target_user_id:
            raise RuntimeError(
                "No profile to attach synthetic journals to. "
                "Set SEED_USER_ID in backend/.env, or call "
                "seed_synthetic_journals(user_id)."
            )

        # Ensure user exists in profiles
        try:
            await conn.execute(
                """
                INSERT INTO profiles (id, onboarding_complete)
                VALUES ($1::uuid, TRUE)
                ON CONFLICT (id) DO NOTHING
                """,
                target_user_id,
            )
        except Exception:
            row = await conn.fetchrow("SELECT id FROM profiles LIMIT 1")
            if row:
                target_user_id = str(row["id"])

        # Fetch existing entries for target user to ensure idempotency
        existing_rows = await conn.fetch(
            "SELECT id, content FROM journal_entries WHERE user_id = $1::uuid;",
            target_user_id,
        )
        existing_by_content = {
            " ".join(r["content"].strip().split()): str(r["id"])
            for r in existing_rows
        }

        for entry_data in DUMMY_JOURNAL_ENTRIES:
            norm_content = " ".join(entry_data["content"].strip().split())
            created_at = datetime.fromisoformat(entry_data["created_at"].replace("Z", "+00:00"))

            # 1. Idempotent check: Insert if not exists, otherwise use existing ID
            if norm_content in existing_by_content:
                entry_id = existing_by_content[norm_content]
            else:
                entry_id = str(uuid.uuid4())
                row = await conn.fetchrow(
                    """
                    INSERT INTO journal_entries (id, user_id, content, created_at)
                    VALUES ($1::uuid, $2::uuid, $3, $4)
                    RETURNING id
                    """,
                    entry_id,
                    target_user_id,
                    entry_data["content"],
                    created_at,
                )
                entry_id = str(row["id"])
                existing_by_content[norm_content] = entry_id

            created_entry_ids.append(entry_id)

            # 2. Run REAL ingestion path (structure-aware chunking + Gemini embedding + journal_chunks insertion)
            chunks = await ingest_journal_entry_asyncpg(
                conn,
                entry_id,
                target_user_id,
                entry_data["content"],
            )
            logger.info("Ingested journal entry %s -> %d chunks", entry_id, len(chunks))

    print(f"Successfully processed {len(created_entry_ids)} synthetic journal entries for user {target_user_id}")
    return target_user_id, created_entry_ids


if __name__ == "__main__":
    asyncio.run(seed_synthetic_journals())
