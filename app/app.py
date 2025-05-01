from flask import Flask, render_template, request, session, send_file
from docx import Document
import os
import webbrowser
from threading import Timer
import pandas as pd
import spacy
import time
import io
from groq import Groq
import difflib
import re
import unicodedata
from collections import Counter
import numpy as np
import matplotlib.pyplot as plt
from collections import Counter
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import base64
from io import BytesIO


app = Flask(__name__)

app.secret_key = 'QyS4YxF3sv8fjN0E-Lw42N9kjyZGoWHJc-rQxH9N1IU'

nlp = spacy.load('en_core_web_md') # en_core_web_sm
nlp.max_length = 10000000

def load_api_key(file_path):
    try:
        with open(file_path, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"API key file not found: {file_path}")
    except Exception as e:
        raise Exception(f"An error occurred while reading the API key: {str(e)}")

API_KEY_FILE = './API.txt'
API = load_api_key(API_KEY_FILE)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'txt', 'docx', 'doc'}


def open_browser():
    webbrowser.open_new('http://127.0.0.1:5000/')


def normalize_text(text):
    text = re.sub(r"^\s+", "", text)
    text = re.sub(r"\s\s+", " ", text)
    text = text.replace("’", "'")
    text = text.replace("‘", "'")
    text = text.replace("“", '"')
    text = text.replace("”", '"')
    text = text.replace("‐", "-")
    text = text.replace("？", "?")
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    return text


def sanitize_filename(filename):
    normalized = unicodedata.normalize('NFC', filename).strip()
    sanitized = re.sub(r'[^\w.\-()]', '_', normalized)
    return sanitized


def safe_division(n, d):
    return n / d if d else 0


def read_file(file_stream, filename):
    try:
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.txt':
            content = file_stream.read().decode('utf-8')
        elif ext == '.docx':
            document = Document(file_stream)
            content = "\n".join([para.text for para in document.paragraphs])
        else:
            content = ""
            print("Unsupported file extension.")
        return content
    except Exception as e:
        print(f"Error reading file: {str(e)}")
        return ""


def extract_t_units(text):
    doc = nlp(text)
    t_units = []
    current_unit = []
    fanboys = ["and", "nor", "but", "or", "yet", "so"]
    conjunctive_adverbs = ["consequently", "therefore", "however", "moreover", "furthermore", "nevertheless", "thus", "hence", "still", "instead", "otherwise", "likewise", "rather", "accordingly", "besides", "alternatively"]
    
    def is_independent_clause(span):
        has_subject = any(token.dep_ in ["nsubj", "nsubjpass"] for token in span)
        has_verb = any(token.pos_ in ["VERB", "AUX"] for token in span)
        return has_subject and has_verb
    
    def shares_same_subject(token):
        if token.dep_ == "conj" and token.head.pos_ == "VERB":
            head_verb = token.head
            for child in head_verb.children:
                if child.dep_ == "nsubj":
                    return True
        return False
    
    def find_next_clause_start(i):
        j = i
        while j < len(doc) and (doc[j].text.lower() in conjunctive_adverbs or
                               doc[j].text in [",", ";"]):
            j += 1
        return j
    
    def should_split_and(token, i):
        if token.text == ";" or (token.text.lower() in conjunctive_adverbs and i > 0 and doc[i-1].text in [";", ","]):
            next_idx = find_next_clause_start(i + 1)
            if next_idx < len(doc):
                next_clause = doc[next_idx:]
                return is_independent_clause(next_clause)
            return False
            
        if token.text.lower() in fanboys and i + 1 < len(doc):
            next_token = doc[i + 1]
            
            if i > 0:
                prev_token = doc[i-1]
                if (prev_token.dep_ == "relcl" or 
                    (prev_token.dep_ == "nsubj" and prev_token.text.lower() == "who") or 
                    token.head.dep_ == "relcl"):
                    return False
            
            if token.dep_ == "cc":
                head = token.head
                if head.pos_ in ["ADJ", "NOUN"]:
                    return False
                if head.dep_ in ["prep", "pobj"] and any(t.dep_ == "prep" for t in doc[i+1:i+3]):
                    return False
                if head.tag_ in ["VBG", "TO", "NN", "NNS"]:
                    return False
                if head.dep_ in ["pcomp", "conj", "dobj", "relcl", "amod", "compound"]:
                    return False
                    
                if i > 0 and i + 2 < len(doc):
                    prev_pos = doc[i-1].pos_
                    next_pos = doc[i+1].pos_
                    if (prev_pos in ["PROPN", "NOUN", "PRON"] and 
                        next_pos in ["PROPN", "NOUN"]):
                        return False
            
            j = i + 1
            while j < len(doc) and doc[j].pos_ not in ["VERB", "AUX", "NOUN", "PRON"]:
                j += 1
    
            if j < len(doc):
                next_verb_or_noun = doc[j]
                
                if next_verb_or_noun.dep_ == "conj":
                    if (next_verb_or_noun.pos_ == "ADJ" or 
                        next_verb_or_noun.head.pos_ == "ADJ" or
                        next_verb_or_noun.pos_ == "PROPN" or
                        next_verb_or_noun.head.pos_ == "PROPN"):
                        return False
                    return False
                
                if any(t.dep_ in ["compound", "amod"] for t in next_verb_or_noun.children):
                    return False
                
                if any(t.dep_ == "xcomp" for t in next_verb_or_noun.children):
                    return False
                
                if next_verb_or_noun.dep_ == "relcl" or (j > 0 and doc[j-1].text.lower() == "who"):
                    return False
                
                if next_verb_or_noun.dep_ in ["nsubj", "nsubjpass"]:
                    if any(t.dep_ == "relcl" for t in doc[i:j+1]):
                        return False
                    if i > 0 and doc[i-1].dep_ in ["nsubj", "nsubjpass"]:
                        return False
                    return True
                
                next_clause = doc[j:]
                return is_independent_clause(next_clause)
    
        return False
    
    split_indices = [0]
    split_pairs = []
    
    for i, token in enumerate(doc):
        if (token.text == ";" or 
            (token.text.lower() in conjunctive_adverbs and i > 0 and doc[i-1].text in [";", ","]) or
            token.text.lower() in fanboys):
            
            if i < len(doc) - 1:
                if should_split_and(token, i):
                    if token.text == ";":
                        split_pairs.append((split_indices[-1], i))
                        split_indices.append(i)
                    else:
                        if i > 0 and doc[i-1].text == ";":
                            split_pairs.append((split_indices[-1], i-1))
                            split_indices.append(i-1)
                        else:
                            split_pairs.append((split_indices[-1], i))
                            split_indices.append(i)
    
    split_pairs.append((split_indices[-1], len(doc)))
    
    for start, end in split_pairs:
        unit_text = ''.join(doc[j].text_with_ws for j in range(start, end))
        if unit_text.strip():
            t_units.append(unit_text.strip())
    
    return t_units


def merge_punctuation(lst):
    if len(lst) < 2:
        return lst
    last_element = lst[-1].strip()
    if last_element in [".", ",", "!", "?", '"', "'"]:
        lst[-2] = lst[-2].rstrip() + last_element
        lst.pop()
    return lst


def is_permissive_construction(token):
    """Returns True if the token is part of a permissive or causative construction."""
    if token.dep_ in ["ccomp", "xcomp"] and token.head.pos_ == "VERB":
        if token.head.lemma_ in ["allow", "let", "help", "make", "have", "get", "want"]:
            return True
        if token.head.dep_ in ["ROOT", "ccomp", "xcomp"]:
            return True
    return False


def extract_verbs(doc):
    clause_verbs = []

    for token in doc:
        if token.dep_ in ["xcomp", "amod"] and token.tag_ == "VBG":
            continue

        if token.pos_ in ["VERB", "AUX"] and token.dep_ not in ["aux"]:
            if any(child.dep_ == "aux" and child.pos_ == "PART" and child.text == "to" for child in token.children):
                continue

            if token.tag_ == "VBG" and token.dep_ not in ["advcl", "acl"]:
                continue

            passive = any(child.dep_ == "auxpass" for child in token.children)
            active = any(child.dep_ in ["nsubj", "csubj", "nsubjpass", "expl"] for child in token.children)

            if active or token.dep_ == "ROOT" or passive or token.dep_ == "advcl" or token.dep_ == "acl":
                clause_verbs.append(token)

        if token.dep_ == "relcl" and token.head.pos_ == "NOUN":
            if token not in clause_verbs:
                clause_verbs.append(token)

    return clause_verbs


def extract_clauses_using_verbs(doc, clause_verbs, extracted_clauses):
    clauses = []
    skip_until = -1

    for verb in clause_verbs:
        clause_tokens = list(verb.subtree)

        if verb.dep_ == "conj" and verb.head.pos_ == "VERB":
            for child in verb.head.children:
                if child.dep_ == "cc" and child.pos_ == "CCONJ":
                    clause_tokens = [child] + clause_tokens
                    break

        if clause_tokens[-1].i + 1 < len(doc) and doc[clause_tokens[-1].i + 1].text in [",", ";", "."]:
            clause_tokens.append(doc[clause_tokens[-1].i + 1])
            skip_until = clause_tokens[-1].i

        clause_text = "".join([t.text_with_ws for t in clause_tokens]).strip()
        
        if clause_text not in extracted_clauses:
            clauses.append(clause_text)

    return clauses


def refine_clauses(clauses):
    clauses_refined = [re.sub(r'\s+([,.;?!])', r'\1', clause).strip() for clause in clauses]

    for i in range(len(clauses_refined)):
        clauses_refined[i] = re.sub(r"\b(\w+)\s+n\s*['’]t", r"\1n't", clauses_refined[i])
        clauses_refined[i] = re.sub(r"\b(I|you|we|they|he|she|it)\s+['’](m|ve|re|d|ll|s)", r"\1'\2", clauses_refined[i])

    refined_clauses = []
    for sentence in clauses_refined:
        sentence = sentence.replace(" ’s", "’s").replace(" 's", "'s").replace(" ’", "'").replace(" '", "'")
        sentence = sentence.replace('“ ', '“').replace(' ”', '”').replace('( ', '(').replace(' )', ')')
        sentence = sentence.replace(' - ', '-')
        refined_clauses.append(sentence)

    return refined_clauses


def add_missing_part(text, output):
    if output:
        first_output = output[0].replace(' ,', ',')
        if first_output in text:
            missing_part = text[:text.index(first_output)].strip()
            output[0] = missing_part + ' ' + output[0].rstrip()

    return output


def compare_and_refine(list_of_sentences):
    refined_list = []
    refined_list.append(list_of_sentences[0].strip())
    
    for i in range(1, len(list_of_sentences)):
        current_sentence = list_of_sentences[i].strip()
        prev_sentence = refined_list[-1]
        
        if current_sentence == prev_sentence:
            continue
            
        if prev_sentence in current_sentence:
            remaining_part = current_sentence[current_sentence.index(prev_sentence) + len(prev_sentence):].strip()
            if remaining_part:
                refined_list.append(remaining_part)
                
        elif current_sentence in prev_sentence:
            start_idx = prev_sentence.index(current_sentence)
            prefix = prev_sentence[:start_idx].strip()
            if prefix:
                refined_list[-1] = prefix
            refined_list.append(current_sentence)
            
        else:
            prev_words = prev_sentence.split()
            current_words = current_sentence.split()
            
            if (len(prev_words) >= 1 and len(current_words) >= 1 and 
                prev_words[-1] == current_words[0]):
                refined_list.append(' '.join(current_words[1:]))
            else:
                refined_list.append(current_sentence)
    
    return refined_list


def process_all_sentences(clauses_only):
    results = []
    for sentence_list in clauses_only:
        refined = compare_and_refine(sentence_list)
        results.append(refined)
    return results


def clausal_complexity(token, feature_dict):
    if token.pos_ == "VERB":
        if token.dep_ != "aux":
            feature_dict["all_clauses"] += 1
            deps = [child.dep_ for child in token.children]
            if "nsubj" in deps or "nsubjpass" in deps:
                feature_dict["finite_clause"] += 1
                if token.dep_ in ["ROOT", "conj"]:
                    feature_dict["finite_ind_clause"] += 1
                else:
                    feature_dict["finite_dep_clause"] += 1
                if token.dep_ == "ccomp":
                    feature_dict["finite_compl_clause"] += 1
                if token.dep_ == "relcl":
                    feature_dict["finite_relative_clause"] += 1
            else:
                feature_dict["nonfinite_clause"] += 1
            feature_dict["vp_deps"] += len(deps)


def calculate_vp_deps(text):
    doc = nlp(text)
    vd_dict = {"vp_deps": 0, "all_clauses": 0, "finite_clause": 0, "finite_ind_clause": 0, 
                    "finite_dep_clause": 0, "finite_compl_clause": 0, "finite_relative_clause": 0, "nonfinite_clause": 0}

    for token in doc:
        if token.pos_ == 'VERB':
            clausal_complexity(token, vd_dict)

    return vd_dict


def noun_phrase_complexity(token, nominal_dict):
    if token.pos_ == "NOUN":  # only consider common nouns (exclude pronouns and proper nouns)
        nominal_dict["np"] += 1
        deps = [child.dep_ for child in token.children]
        nominal_dict["np_deps"] += len(deps)
        for x in deps:
            if x == "relcl":
                nominal_dict["relcl_dep"] += 1
            if x == "amod":
                nominal_dict["amod_dep"] += 1
            if x == "det":
                nominal_dict["det_dep"] += 1
            if x == "prep":
                nominal_dict["prep_dep"] += 1
            if x == "poss":
                nominal_dict["poss_dep"] += 1
            if x == "cc":
                nominal_dict["cc_dep"] += 1


def calculate_nominal_deps(text):
    doc = nlp(text)
    nominal_dict = {"np": 0, "np_deps": 0, "relcl_dep": 0, "amod_dep": 0, "det_dep": 0, "prep_dep": 0, "poss_dep": 0, "cc_dep": 0}

    for token in doc:
        noun_phrase_complexity(token, nominal_dict)

    return nominal_dict
   

def calculate_errors(original, corrected):
    original_words = original.split()
    corrected_words = corrected.split()
    matcher = difflib.SequenceMatcher(None, original_words, corrected_words)
    errors = 0
    highlighted_original = []
    highlighted_corrected = []
    for opcode in matcher.get_opcodes():
        tag, i1, i2, j1, j2 = opcode
        if tag == 'equal':
            highlighted_original.extend(original_words[i1:i2])
            highlighted_corrected.extend(corrected_words[j1:j2])
        elif tag == 'replace':
            highlighted_original.append('<strong>{}</strong>'.format(' '.join(original_words[i1:i2])))
            highlighted_corrected.append('<strong>{}</strong>'.format(' '.join(corrected_words[j1:j2])))
            errors += 1
        elif tag == 'insert':
            highlighted_corrected.append('<strong>{}</strong>'.format(' '.join(corrected_words[j1:j2])))
            errors += 1
        elif tag == 'delete':
            highlighted_original.append('<strong>{}</strong>'.format(' '.join(original_words[i1:i2])))
            errors += 1
    return errors, ' '.join(highlighted_original), ' '.join(highlighted_corrected)





def extract_error_snippets(original, corrected):
    """
    Extract highlighted error locations (surrounded by <strong></strong>)
    """
    original_errors = re.findall(r'<strong>(.*?)</strong>', original)
    corrected_errors = re.findall(r'<strong>(.*?)</strong>', corrected)
    
    # Return empty list if no highlights found
    if not original_errors and not corrected_errors:
        return []
    
    # Create pairs of errors and corrections
    error_pairs = []
    for i in range(max(len(original_errors), len(corrected_errors))):
        orig = original_errors[i] if i < len(original_errors) else ""
        corr = corrected_errors[i] if i < len(corrected_errors) else ""
        error_pairs.append((orig, corr))
    
    return error_pairs

def classify_errors_with_llama(corrected_data, model_name="llama-3.3-70b-versatile", delay=1, batch_size=5):

    try:
        API_KEY_FILE = './API.txt'
        with open(API_KEY_FILE, 'r') as file:
            api_key = file.read().strip()
        client = Groq(api_key=api_key)
    except Exception as e:
        print(f"Error initializing Groq client: {e}")
        corrected_data['ErrorCategories'] = corrected_data.apply(
            lambda row: ', '.join(['OTHER'] * row['Error Counts']) if row['Error Counts'] > 0 else 'NO_ERROR', 
            axis=1
        )
        return corrected_data

    corrected_data['ErrorCategories'] = ''
    corrected_data['Error_Category_Mapping'] = ''
    
    category_descriptions = """
- ART: Article errors (a, an, the)
  Example: "I agree with following statement." => "I agree with the following statement."
- PREP: Preposition errors (in, on, at, by, etc.)
  Example: "They need to solve these problems in themselves." => "They need to solve these problems by themselves."
- NUM: Number errors (singular/plural)
  Example: "It contributes to their future job." => "It contributes to their future jobs."
- TENSE: Verb tense errors (past, present, future)
  Example: "After students graduated, almost all of them will start working." => "After students graduate, almost all of them will start working."
- VFORM: Verb form errors (infinitive, gerund, etc.)
  Example: "They can acquire the skill of talk with their customers." => "They can acquire the skill of talking with their customers."
- WO: Word order errors
  Example: "This ability will be also useful after they get their jobs." => "This ability will also be useful after they get their jobs."
- AGR: Subject-verb agreement errors
  Example: "College students needs a lot of money." => "College students need a lot of money."
- DET: Determiner errors (not articles)
  Example: "Students should have their part-time job." => "Students should have a part-time job."
- POSS: Possession/belonging errors
  Example: "He forgot brother birthday." => "He forgot his brother's birthday."
- MOD: Modal verb errors
  Example: "Many students maybe worry about their future." => "Many students may worry about their future."
- CONJ: Conjunction errors
  Example: "One is the desire to learn, the other is the willingness to try." => "One is the desire to learn, and the other is the willingness to try."
- STRUCT: Structural errors
  Example: "Students have to be careful to work long hours." => "Students have to be careful when they work long hours."
- N: Noun replacement
  Example: "It is necessary to know the hardness of earning money." => "It is necessary to know the hardship of earning money."
- ADJ: Adjective replacement
  Example: "Their ages are so variety." => "Their ages are so varied."
- ADV: Adverb replacement
  Example: "He goes home tiredly." => "He goes home tired."
- V: Verb replacement (meaning change)
  Example: "Many people give money from their parents." => "Many people receive money from their parents."
- REF: Reference errors (pronouns, demonstratives)
  Example: "We do not learn how to communicate with your coworkers." => "We do not learn how to communicate with our coworkers."
- EXPR: Expression replacements
  Example: "College students should live themselves." => "College students should live on their own."
- SP: Spelling errors
  Example: "I want moeny to buy something I want." => "I want money to buy something I want."
- MIS: Missing word (not article or preposition)
  Example: "They have to respect to their customers." => "They have to show respect to their customers."
- UNN: Unnecessary word
  Example: "I agree with that it is important for students to have a part-time job." => "I agree that it is important for students to have a part-time job."
- CWS: Compound word spacing
  Example: "We can not do what we want to do." => "We cannot do what we want to do."
- PUNC: Punctuation errors
  Example: "I am 19 and my boss is over 40." => "I am 19, and my boss is over 40."
"""
    
    batch_prompt_template = """
You are a linguistic expert specializing in English grammar and error analysis. Analyze each of the following errors and assign the most appropriate error category to each.

{error_items}

Classify each error using ONLY ONE of the following categories:
{categories}

Guidelines for classifying errors:
1. Look at the context of the error, not just the error itself
2. Compare the original and corrected sentences to understand what changed
3. Some errors might fit multiple categories - choose the most specific and accurate one
4. Pay attention to the examples provided for each category to guide your classification
5. Only use the categories listed above - do not create new categories

For each error, reply with ONLY the error number and category code (e.g., "1. ART", "2. PREP", etc.). 
Put each error on a new line. Do not include any explanations or additional text.
"""
    
    error_item_template = """
Error {number}:
Original sentence: "{original}"
Corrected sentence: "{corrected}"
Specific error: "{error}" => "{correction}"
"""
    
    all_error_pairs = []
    row_indices = []
    pair_indices = []
    
    for idx, row in corrected_data.iterrows():
        if row['Error Counts'] > 0:
            original_sentence = row['Sentence']
            corrected_sentence = row['Corrected']
            original_highlighted = row['Highlighted Original']
            corrected_highlighted = row['Highlighted Corrected']
            
            error_pairs = extract_error_snippets(original_highlighted, corrected_highlighted)
            
            for pair_idx, (orig, corr) in enumerate(error_pairs):
                all_error_pairs.append({
                    'original_sentence': original_sentence,
                    'corrected_sentence': corrected_sentence,
                    'error_text': orig,
                    'correction_text': corr
                })
                row_indices.append(idx)
                pair_indices.append(pair_idx)
    
    total_errors = len(all_error_pairs)
    all_categories = [None] * total_errors
        
    for i in range(0, total_errors, batch_size):
        batch_errors = all_error_pairs[i:min(i+batch_size, total_errors)]
        
        error_items = ""
        for j, error_pair in enumerate(batch_errors):
            error_items += error_item_template.format(
                number=j+1,
                original=error_pair['original_sentence'],
                corrected=error_pair['corrected_sentence'],
                error=error_pair['error_text'],
                correction=error_pair['correction_text']
            )
        
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a linguistic error analysis expert specialized in English grammar and error classification."},
                    {"role": "user", "content": batch_prompt_template.format(
                        error_items=error_items,
                        categories=category_descriptions
                    )}
                ],
                model=model_name,
                temperature=0,
            )
            
            response = chat_completion.choices[0].message.content.strip()
            
            category_pattern = r'(\d+)\.\s+([A-Z]+)'
            matches = re.findall(category_pattern, response)
            
            for match in matches:
                error_num = int(match[0]) - 1
                category = match[1].strip()
                
                if error_num < len(batch_errors):
                    # カテゴリーを保存
                    batch_index = i + error_num
                    if batch_index < total_errors:
                        all_categories[batch_index] = category
            
            if delay > 0:
                time.sleep(delay)
                
        except Exception as e:
            print(f"Error in batch {i//batch_size + 1}: {e}")
            for j in range(len(batch_errors)):
                batch_index = i + j
                if batch_index < total_errors:
                    all_categories[batch_index] = "OTHER"
    
    row_categories = {idx: [] for idx in corrected_data.index}
    row_mappings = {idx: [] for idx in corrected_data.index}
    
    for i, category in enumerate(all_categories):
        if category:
            row_idx = row_indices[i]
            pair_idx = pair_indices[i]
            row_categories[row_idx].append(category)
            
            error_pair = all_error_pairs[i]
            error_text = error_pair['error_text']
            correction_text = error_pair['correction_text']
            
            mapping = f"'{error_text}' => '{correction_text}' [{category}]"
            row_mappings[row_idx].append(mapping)
    
    for idx in corrected_data.index:
        categories = row_categories.get(idx, [])
        mappings = row_mappings.get(idx, [])
        corrected_data.at[idx, 'ErrorCategories'] = ', '.join(categories) if categories else 'NO_ERROR'
        corrected_data.at[idx, 'Error_Category_Mapping'] = '; '.join(mappings) if mappings else 'NO_ERROR'
    
    category_counts = Counter()
    for categories_str in corrected_data['ErrorCategories']:
        if pd.notna(categories_str) and categories_str != 'NO_ERROR':
            for category in categories_str.split(', '):
                category_counts[category] += 1
    
    return corrected_data



def correct_sentences(data):
    client = Groq(api_key=API)
    prompt = "Reply with a corrected version of the input sentence with all grammatical, spelling, and punctuation errors fixed. Be strict about the possible errors. If there are no errors, reply with a copy of the original sentence. Please do not add any unnecessary explanations."

    for index, row in data.iterrows():
        text = row['Sentence']
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0,       
        )
        response = chat_completion.choices[0].message.content

        error_count, original_highlighted, corrected_highlighted = calculate_errors(text, response)

        data.loc[index, 'Corrected'] = response
        data.loc[index, 'Highlighted Original'] = original_highlighted
        data.loc[index, 'Highlighted Corrected'] = corrected_highlighted
        data.loc[index, 'Error Counts'] = error_count

        #time.sleep(1)

    return data


def check_error_in_t_units(corrected_list, t_units_list):
    error_report = []
    t_units_counts = []
    error_free_t_unit = []
    
    for i, t_units in enumerate(t_units_list):
        corrected_sentence = corrected_list[i]
        t_unit_errors = []
        no_error_count = 0
        
        for t_unit in t_units:
            if t_unit.strip() not in corrected_sentence:
                t_unit_errors.append((t_unit, "Error"))
            else:
                t_unit_errors.append((t_unit, "No Error"))
                no_error_count += 1
        
        error_report.append(t_unit_errors)
        t_units_counts.append(len(t_units))
        error_free_t_unit.append(no_error_count)

    return error_report, t_units_counts, error_free_t_unit


def check_errors_in_t_units_and_clauses(corrected_list, t_units_list, clauses_refined):
    t_units_counts = []
    clauses_counts = []
    error_free_t_unit = []
    error_free_clause = []

    for i in range(len(corrected_list)):
        corrected_sentence = corrected_list[i]

        t_units = t_units_list[i]
        t_unit_errors = []
        no_error_t_units_count = 0

        for t_unit in t_units:
            if t_unit.strip() not in corrected_sentence:
                t_unit_errors.append((t_unit, "Error"))
            else:
                t_unit_errors.append((t_unit, "No Error"))
                no_error_t_units_count += 1

        t_units_counts.append(len(t_units))
        error_free_t_unit.append(no_error_t_units_count)

        clauses = clauses_refined[i]
        clause_errors = []
        no_error_clauses_count = 0

        for clause in clauses:
            if clause.strip() not in corrected_sentence:
                clause_errors.append((clause, "Error"))
            else:
                clause_errors.append((clause, "No Error"))
                no_error_clauses_count += 1

        clauses_counts.append(len(clauses))
        error_free_clause.append(no_error_clauses_count)

    return {
        't_units_counts': t_units_counts,
        'clauses_counts': clauses_counts,
        'error_free_t_unit': error_free_t_unit,
        'error_free_clause': error_free_clause
    }


def generate_error_chart(category_counts):
    """Generate a horizontal bar chart for error categories and return as base64 encoded image"""
    # Create horizontal bar chart for error categories
    fig = Figure(figsize=(12, 8))
    ax = fig.add_subplot(111)
    
    # Get categories and counts in most common order
    categories = [c for c, _ in category_counts.most_common()]
    counts = [count for _, count in category_counts.most_common()]
    
    # Reverse the lists to change the y-axis order
    categories = categories[::-1]
    counts = counts[::-1]
    
    y_pos = np.arange(len(categories))
    bars = ax.barh(y_pos, counts, align='center', color='steelblue')
    ax.set_yticks(y_pos)
    ax.set_yticklabels(categories)
    ax.set_title('Error Type Distribution')
    ax.set_xlabel('Count')
    
    # Set integer ticks on x-axis
    max_count = max(counts) if counts else 0
    ax.set_xticks(np.arange(0, max_count + 1, step=1))
    
    # Add count labels for all bars
    for i, bar in enumerate(bars):
        width = bar.get_width()
        # Make sure labels for small bars are visible by placing them slightly to the right
        if width < 0.7:
            # Place text to the right of small bars
            ax.text(width + 0.1, bar.get_y() + bar.get_height()/2, 
                   f'{int(width)}', ha='left', va='center', 
                   color='black', fontweight='bold')
        else:
            # Place text inside the bar for larger bars
            ax.text(width/2, bar.get_y() + bar.get_height()/2, 
                   f'{int(width)}', ha='center', va='center', 
                   color='white', fontweight='bold')
    
    fig.tight_layout()
    
    # Save to BytesIO object
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=300, bbox_inches='tight')
    buf.seek(0)
    
    # Encode the image to base64 string
    img_str = base64.b64encode(buf.getvalue()).decode('utf-8')
    return img_str



######################################################################

@app.route('/', methods=['POST', 'GET'])
def home():
    try:
        text = ''
        e_time = ''
        fluencytable = pd.DataFrame()
        complexitytable = pd.DataFrame()
        accuracytytable = pd.DataFrame()
        data = pd.DataFrame()
        corrected_data = pd.DataFrame()
        output_data = pd.DataFrame()
        error_chart_b64 = None
        category_counts = Counter()


        if request.method == 'POST':
            file = request.files.get('file')
            if file and allowed_file(file.filename):
                filename = sanitize_filename(file.filename)
                session['file_name'] = filename

                try:
                    file_stream = io.BytesIO(file.read())
                    text = read_file(file_stream, filename)

                except Exception as e:
                    print(f"File reading error: {str(e)}")
                    return f"File reading error: {str(e)}"
            else:
                session.pop('file_name', None)
                text = request.form.get('text', '')
            
            
            text = normalize_text(text)

                        
            start = time.time()


    ### Fluency ###
            doc = nlp(text)

            num_sentences = len(list(doc.sents))

            total_words = 0
            sentslist = []
            for sentence in doc.sents:
                num_tokens = sum(1 for token in sentence if token.pos_ not in ["PUNCT", "SYM", "SPACE", "X"])  # Following TASSC_20058_stable.py
                total_words += num_tokens
                sentslist.append(sentence.text) 

            tokens = [token.text.lower() for token in doc if not token.is_punct and not token.is_space]
            type_count = len(set(tokens))

            #ttr = safe_division(type_count, total_words)
            #mls = safe_division(total_words, num_sentences)

            fluencytable = pd.DataFrame({
                "Index": ["Total Number of Words", "Number of Types", "Number of Sentences"], #"Mean Length of Sentence (MLS)"
                "Value": [total_words, type_count, num_sentences] # f"{mls:.2f}"
            })


    ### Complexity ###
            total_t_units = 0
            t_units_list = []
            clausal_data = []
            num_clauses = 0

            for i in sentslist:
                t_units = extract_t_units(i)
                filtered_t_units = [t for t in t_units if t]
                filtered_t_units = merge_punctuation(filtered_t_units)
                t_units_list.append(filtered_t_units)
                total_t_units += len(filtered_t_units)

                doc = nlp(i)
                clause_verbs = extract_verbs(doc)
                    
                clausal_data.append({
                    "sentence": i,
                    "total_clauses": len(clause_verbs),
                    "clause_verbs": clause_verbs
                })

                matched_t_units = []
                for t_unit, clause_info in zip(t_units_list, clausal_data):
                    if len(t_unit) == clause_info['total_clauses']:
                        matched_t_units.append(t_unit)
                    elif clause_info['total_clauses'] == 0:
                        matched_t_units.append(t_unit)        
                    else:
                        doc = nlp(clause_info['sentence'])
                        clause_verbs = extract_verbs(doc)
                        extracted_clauses = []
                        clauses = extract_clauses_using_verbs(doc, clause_verbs, extracted_clauses)
                        clauses_refined = refine_clauses(clauses)
                        output_with_missing_part = add_missing_part(clause_info['sentence'], clauses_refined)
                        output_with_missing_part = refine_clauses(output_with_missing_part)

                        if len(output_with_missing_part) == clause_info['total_clauses']:
                            matched_t_units.append(output_with_missing_part)

                clauses_only = []
                for t_unit in matched_t_units:
                    clauses_only.append(t_unit)

                clauses_refined = process_all_sentences(clauses_only)

                for i in range(len(clauses_refined)):
                    for j in range(len(clauses_refined[i]) - 1):
                        doc = nlp(clauses_refined[i][j])
                        last_token = doc[-1]
                        
                        if last_token.text.lower() in ["and", "but"] and last_token.pos_ == "CCONJ":
                            clauses_refined[i][j] = ''.join([token.text_with_ws for token in doc[:-1]]).strip()
                            clauses_refined[i][j + 1] = f"{last_token.text} {clauses_refined[i][j + 1]}"

                        elif last_token.text.lower() == "as":
                            clauses_refined[i][j] = ''.join([token.text_with_ws for token in doc[:-1]]).strip()
                            if j + 1 < len(clauses_refined[i]):
                                clauses_refined[i][j + 1] = f"as {clauses_refined[i][j + 1]}"
                            elif i + 1 < len(clauses_refined):
                                clauses_refined[i + 1].insert(0, f"as {clauses_refined[i + 1][0]}")

                clauses_refined = [[clause.replace(' ,', ',').replace(' .', '.').replace(' ?', '?').replace(' !', '!') for clause in sublist] for sublist in clauses_refined]

                num_clauses = sum(len(clause) for clause in clauses_refined)

            joined_string = " ".join(sentslist)
            vd_features = calculate_vp_deps(joined_string)
            nominal_features = calculate_nominal_deps(joined_string)

            mlc = format(safe_division(total_words, num_clauses), ".2f")
            mlt = format(safe_division(total_words, total_t_units), ".2f")
            c_t = format(safe_division(num_clauses, total_t_units), ".2f")

            dc_t = format(safe_division(vd_features["finite_dep_clause"], total_t_units), ".2f")
            dc_c = format(safe_division(vd_features["finite_dep_clause"], num_clauses), ".2f")

            mvd = format(safe_division(vd_features["vp_deps"], vd_features["finite_clause"]), ".2f")
            mnd = format(safe_division(nominal_features["np_deps"], nominal_features["np"]), ".2f")
            mls = safe_division(total_words, num_sentences)

            complexitytable = pd.DataFrame({
                "Index": ["Mean Length of Sentence (MLS)", "Number of T-units", "Number of Clauses", "Mean Length of T-Unit (MLT)", 
                          "Mean Length of Clause (MLC)", "Clauses per T-unit (C/T)"], #"Dependent Clauses per T-unit (DC/T)", "Dependent Clauses per Clause (DC/C)", "Mean Verbal Dependents", "Mean Nominal Dependents"
                "Value": [f"{mls:.2f}", total_t_units, num_clauses, mlt, mlc, c_t] # dc_t, dc_c, mvd, mnd
            })


    ### Accuracy ###
            data = pd.DataFrame(sentslist, columns=['Sentence'])
            corrected_data = correct_sentences(data)
            corrected_data['Error Counts'] = corrected_data['Error Counts'].astype(int)
            corrected_data.index = corrected_data.index + 1

            corrected_list = corrected_data['Corrected'].tolist()

            error_report, t_units_counts, error_free_t_unit = check_error_in_t_units(corrected_list, t_units_list)

            clause_verbs_list = [entry['clause_verbs'] for entry in clausal_data]

            result = check_errors_in_t_units_and_clauses(corrected_list, t_units_list, clauses_refined)

            error_free_t_unit = result['error_free_t_unit']
            error_free_clause = result['error_free_clause']

            corrected_data['T-unit counts'] = result['t_units_counts']
            corrected_data['Error-free T-units'] = result['error_free_t_unit']
            corrected_data['Clause counts'] = result['clauses_counts']
            corrected_data['Error-free clauses'] = result['error_free_clause']
            corrected_data['Extracted T-units'] = t_units_list
            corrected_data['Extracted clauses'] = clauses_refined
            corrected_data['Clause signaling verbs'] = clause_verbs_list

            corrected_data = classify_errors_with_llama(corrected_data)

            category_counts = Counter()
            for categories_str in corrected_data['ErrorCategories']:
                if pd.notna(categories_str) and categories_str != 'NO_ERROR':
                    for category in categories_str.split(', '):
                        category_counts[category] += 1
            
            if sum(category_counts.values()) > 0:
                error_chart_b64 = generate_error_chart(category_counts)
                
            csv_data = corrected_data.copy()
            csv_data['Highlighted Original'] = csv_data['Highlighted Original'].str.replace('<strong>', '**')
            csv_data['Highlighted Original'] = csv_data['Highlighted Original'].str.replace('</strong>', '**')
            csv_data['Highlighted Corrected'] = csv_data['Highlighted Corrected'].str.replace('<strong>', '**')
            csv_data['Highlighted Corrected'] = csv_data['Highlighted Corrected'].str.replace('</strong>', '**')

            output_data['Original'] = corrected_data['Highlighted Original']
            output_data['Corrected'] = corrected_data['Highlighted Corrected']
            output_data['Error Counts'] = corrected_data['Error Counts'].copy()
            output_data['Error Types'] = corrected_data['ErrorCategories']

            csv_data.to_csv("static/files/corrected.csv", sep=",", index=False)

            total_clauses = corrected_data['Clause counts'].sum()
            errorfree_sent_count = (corrected_data['Error Counts'] == 0).sum()
            errorfree_t_unit_count = corrected_data['Error-free T-units'].sum()
            errorfree_clause_count = corrected_data['Error-free clauses'].sum()

            # (1) Total Errors
            total_errors = corrected_data['Error Counts'].sum()
            # (2) Errors per 100 Words
            errors_per_hundred_words = (total_errors / total_words) * 100
            formatted_errors = format(errors_per_hundred_words, ".2f")
            # (3) Errors per Total Words
            number_of_errors_per_words = format(safe_division(total_errors, total_words), ".2f")
            # (4) Errors per sentences (errors / num_sentences)
            errors_per_sentence = format(safe_division(total_errors, num_sentences), ".2f")
            # (5) Errors per T-unit
            number_of_errors_per_t_unit = format(safe_division(total_errors, total_t_units), ".2f")
            # (6) Errors per Clause
            number_of_errors_per_clause = format(safe_division(total_errors, total_clauses), ".2f")
            # (7) Error-Free Sentences
            error_free_sentence = errorfree_sent_count
            # (8) Error-free T-units
            error_free_t_unit = errorfree_t_unit_count
            # (9) Error-free Clauses
            error_free_clause = errorfree_clause_count
            # (10) Error-Free Sentences / Sentences
            error_free_sentence_ratio = format(round(safe_division(errorfree_sent_count, num_sentences), 2), ".2f")
            # (11) Error-Free T-units / T-units
            error_free_t_unit_ratio = format(round(safe_division(errorfree_t_unit_count, total_t_units), 2), ".2f")
            # (12) Error-Free Clauses / Clauses
            error_free_clause_ratio = format(round(safe_division(errorfree_clause_count, total_clauses), 2), ".2f")

            accuracytytable = pd.DataFrame({
                "Index": [
                    "Number of Errors", 
                    "Errors per 100 Words", 
                    "Errors per Total Words", 
                    "Errors per Sentence",
                    "Errors per T-Unit", 
                    "Errors per Clause", 
                    "Error-Free Sentences",
                    "Error-Free T-Units", 
                    "Error-Free Clauses", 
                    "Error-Free Sentences / Total Sentences",
                    "Error-Free T-Units / Total T-units",
                    "Error-Free Clauses / Total Clauses"
                ],
                "Value": [
                    total_errors, 
                    formatted_errors, 
                    number_of_errors_per_words, 
                    errors_per_sentence,
                    number_of_errors_per_t_unit, 
                    number_of_errors_per_clause, 
                    error_free_sentence, 
                    error_free_t_unit, 
                    error_free_clause, 
                    error_free_sentence_ratio, 
                    error_free_t_unit_ratio,
                    error_free_clause_ratio
                ]
            })
                


            e_time = time.time() - start
            e_time = f"{e_time:.2f}" 



        file_name = session.get('file_name', '')
        
        return render_template('main.html', 
                               table1=[fluencytable.to_html(index=False)], 
                               table2=[complexitytable.to_html(index=False)],
                               table3=[accuracytytable.to_html(index=False)], 
                               table4=[output_data.to_html(classes='data', header="true", index=True, escape=False)],
                               texts=text, 
                               e_time=e_time, 
                               file_name=file_name,
                               error_chart=error_chart_b64,
                               error_counts=category_counts) 
    except Exception as e:
        return str(e), 500
    


@app.route('/downloader')
def downloader():
    return send_file('./static/files/corrected.csv',
                     mimetype='text/csv',
                     download_name='Downloaded.csv',
                     as_attachment=True)


if __name__ == "__main__":
    Timer(1, open_browser).start()
    app.run(port=5000, threaded=False)
    #app.run(debug=True, threaded=True) # For online deployment
