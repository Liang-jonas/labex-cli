import re
import requests
from datetime import datetime, timedelta
from .utils.feishu import Feishu


class GitHub:
    """GitHub 相关 API"""

    def __init__(self, token: str) -> None:
        self.token = token

    def get_issues_list(self, repo_name: str) -> list:
        """获取 issues 列表

        Args:
            repo_name (str): 仓库名称
        """
        url = f"https://api.github.com/repos/{repo_name}/issues"
        headers = {
            "Authorization": "token " + self.token,
            "Accept": "application/vnd.github+json",
        }
        params = {
            "state": "all",
            "per_page": 100,
        }

        all_issues = []
        page = 1

        while True:
            params["page"] = page
            print(f"Fetching page {page} of issues...")
            response = requests.get(url, headers=headers, params=params)
            if response.status_code != 200:
                raise Exception(
                    f"Error retrieving issues: {response.status_code}, {response.text}"
                )

            issues = response.json()
            if not issues:
                break

            all_issues.extend(issues)
            page += 1

        # 仅保留 Issue，去掉 PR
        noly_issues = [i for i in all_issues if "pull_request" not in i.keys()]

        return noly_issues


class SyncIssuesToFeishu:
    def __init__(self, app_id: str, app_secret: str, ghtoken: str) -> None:
        self.github = GitHub(token=ghtoken)
        self.feishu = Feishu(app_id, app_secret)
        self.app_token = "bascnNz4Nqjqgqm1Nm5AYke6xxb"
        self.table_id = "tblLnz5UqvvHb5Z0"
        self.skills_table_id = "tblV5pGIsGZMxmE9"

    def unix_ms_timestamp(self, time_str: str) -> int:
        if time_str != None:
            date_obj = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ") + timedelta(
                hours=8
            )
            unix_ms_timestamp = int(date_obj.timestamp() * 1000)
        else:
            unix_ms_timestamp = 946656000000
        return unix_ms_timestamp

    def sync_issues(self, repo_name: str) -> None:
        # Get all skills from feishu
        skills = self.feishu.get_bitable_records(
            self.app_token, self.skills_table_id, params=""
        )
        # Make a dict of skill and record_id
        skills_dicts = {
            r["fields"]["SKILL_ID"][0]["text"]: r["record_id"] for r in skills
        }
        print(f"Found {len(skills_dicts)} skills in Feishu.")
        # Get all records from feishu
        records = self.feishu.get_bitable_records(
            self.app_token, self.table_id, params=""
        )
        # Make a dict of ISSUE_NUM and record_id
        records_dicts = {r["fields"]["ISSUE_NUM"]: r["record_id"] for r in records}
        # Get all issues from github
        issues_list = self.github.get_issues_list(repo_name)
        print(f"Found {len(issues_list)} issues in GitHub.")
        # Feishu 未关闭的 Issue
        feishu_not_closed_issue_nums = [
            str(r["fields"]["ISSUE_NUM"])
            for r in records
            if r["fields"]["ISSUE_STATE"] == "OPEN"
        ]
        print(f"Found {len(feishu_not_closed_issue_nums)} OPEN ISSUE in Feishu.")
        # 忽略已经关闭的 ISSUE
        issues_list = [
            issue
            for issue in issues_list
            if issue["state"] == "open"
            or str(issue["number"]) in feishu_not_closed_issue_nums
        ]
        # 忽略 locked 的 issue
        issues_list = [issue for issue in issues_list if issue["locked"] == False]
        print(f"Processing {len(issues_list)} OPEN issue...")
        for issue in issues_list:
            try:
                issue_title = issue["title"]
                issue_number = issue["number"]
                issue_state = issue["state"]
                issue_user = issue["user"]["login"]
                issues_html_url = issue["html_url"]
                created_at = self.unix_ms_timestamp(issue["created_at"])
                updated_at = self.unix_ms_timestamp(issue["updated_at"])
                closed_at = self.unix_ms_timestamp(issue["closed_at"])
                # assignees
                assignees = issue["assignees"]
                if len(assignees) == 0:
                    assignees = []
                else:
                    assignees = [a["login"] for a in assignees]
                # labels
                issues_labels = issue["labels"]
                if len(issues_labels) == 0:
                    issues_labels = []
                else:
                    issues_labels = [l["name"] for l in issues_labels]
                # skills
                issues_body = issue["body"]
                skills = re.findall(r"`\w+/\w+`", issues_body)
                if len(skills) == 0:
                    skills = []
                else:
                    skills = [s.replace("`", "").replace(" ", "") for s in skills]
                # steps
                steps = re.findall(r"建议步骤数\*\*:(.*[0-9])", issues_body)
                if len(steps) == 0:
                    steps_num = 0
                else:
                    try:
                        steps_num = int(steps[0].strip())
                    except:
                        steps_num = 0
                # search skills in feishu
                skills_record_ids = []
                for skill in skills:
                    if skill in skills_dicts.keys():
                        skills_record_ids.append(skills_dicts[skill])
                # payloads
                payloads = {
                    "fields": {
                        "ISSUE_TITLE": issue_title,
                        "ISSUE_NUM": issue_number,
                        "ISSUE_STATE": issue_state.upper(),
                        "ISSUE_USER": issue_user,
                        "ISSUE_STEPS": steps_num,
                        "CREATED_AT": created_at,
                        "UPDATED_AT": updated_at,
                        "CLOSED_AT": closed_at,
                        "HTML_URL": {
                            "link": issues_html_url,
                            "text": "OPEN IN GITHUB",
                        },
                        "ASSIGNEES": assignees,
                        "ISSUE_LABELS": issues_labels,
                        "SCENARIO_SKILLS": skills_record_ids,
                        "SKILLS": skills,
                        "ISSUE_BODY": issues_body,
                    }
                }
                # Update record
                if str(issue_number) in records_dicts.keys():
                    r = self.feishu.update_bitable_record(
                        self.app_token,
                        self.table_id,
                        records_dicts[str(issue_number)],
                        payloads,
                    )
                    print(f"→ Updating {issue_title} {r['msg'].upper()}")
                else:
                    # Add record
                    r = self.feishu.add_bitable_record(
                        self.app_token, self.table_id, payloads
                    )
                    print(f"↑ Adding {issue_title} {r['msg'].upper()}")

            except Exception as e:
                print(f"Exception: {e}")
                continue
