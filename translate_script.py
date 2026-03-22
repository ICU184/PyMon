import os
import glob

replacements = {
    # General UI Terms
    '"Refresh"': '"Refresh"',
    "'Refresh'": "'Refresh'",
    '"Cancel"': '"Cancel"',
    "'Cancel'": "'Cancel'",
    '"Close"': '"Close"',
    "'Close'": "'Close'",
    '"Save"': '"Save"',
    "'Save'": "'Save'",
    '"Success"': '"Success"',
    "'Success'": "'Success'",
    '"Error"': '"Error"',
    "'Error'": "'Error'",
    '"Warning"': '"Warning"',
    "'Warning'": "'Warning'",
    '"Settings"': '"Settings"',
    "'Settings'": "'Settings'",
    '"Loading..."': '"Loading..."',
    "'Loading...'": "'Loading...'",
    '"Loading…"': '"Loading…"',
    "'Loading…'": "'Loading…'",
    '"Search"': '"Search"',
    "'Search'": "'Search'",
    '"No data"': '"No data"',
    "'No data'": "'No data'",

    # Date / Time
    '"Today"': '"Today"',
    "'Today'": "'Today'",
    '"Yesterday"': '"Yesterday"',
    "'Yesterday'": "'Yesterday'",
    '"This Week"': '"This Week"',
    "'This Week'": "'This Week'",
    '"This Month"': '"This Month"',
    "'This Month'": "'This Month'",
    '"Last Month"': '"Last Month"',
    "'Last Month'": "'Last Month'",
    '"Year"': '"Year"',
    "'Year'": "'Year'",
    '"Month"': '"Month"',
    "'Month'": "'Month'",
    '"Day"': '"Day"',
    "'Day'": "'Day'",

    # Specific to PyMon UI
    '"Total"': '"Total"',
    "'Total'": "'Total'",
    '"Name"': '"Name"',
    '"Type"': '"Type"',
    '"Value"': '"Value"',
    '"Quantity"': '"Quantity"',
    '"Price"': '"Price"',
    '"Skillpoints"': '"Skillpoints"',
    '"Skills"': '"Skills"',
    '"Certificates"': '"Certificates"',
    '"Ships"': '"Ships"',
    '"Books"': '"Books"',
    '"Attributes"': '"Attributes"',
    '"Description"': '"Description"',
    '"Time"': '"Time"',
    '"Route Planner"': '"Route Planner"',
    '"Data Browser"': '"Data Browser"',
    '"Certificate Browser"': '"Certificate Browser"',
    '"Owned Skillbooks"': '"Owned Skillbooks"',
    '"Ship Browser"': '"Ship Browser"',
}

def translate_files():
    search_path = "C:/Users/user/Documents/Python/PyMon/**/*.py"
    for filepath in glob.glob(search_path, recursive=True):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            new_content = content
            for german, english in replacements.items():
                new_content = new_content.replace(german, english)
            
            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"Translated: {filepath}")
        except Exception as e:
            print(f"Failed to process {filepath}: {e}")

if __name__ == "__main__":
    translate_files()
