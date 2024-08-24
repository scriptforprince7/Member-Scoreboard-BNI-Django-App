from django.http import HttpResponse
from django.shortcuts import render
import pandas as pd
from django.shortcuts import render
from django.http import JsonResponse
from django.core.files.storage import FileSystemStorage
from openpyxl.utils.exceptions import InvalidFileException
from django.urls import reverse
from pandas.errors import EmptyDataError, ParserError
from io import BytesIO


def home(request):

    has_data = bool(request.session.get('member_data')) and bool(request.session.get('palms_data'))

    context = {
        'has_data': has_data
    }
    return render(request, 'home.html', context)


def upload_both_reports(request):
    if request.method == 'POST':
        chapter_name = request.POST.get('chapter_name')
        member_file = request.FILES.get('member_file')
        palms_file = request.FILES.get('palms_file')

        if not (member_file and palms_file):
            return JsonResponse({'status': 'error', 'message': 'Please upload both files.'})

        if not chapter_name:
            return JsonResponse({'status': 'error', 'message': 'Please enter a chapter name.'})

        # Save and process the Member Training Report file
        if not member_file.name.endswith('.xlsx'):
            return JsonResponse({'status': 'error', 'message': 'Please upload a valid .xlsx file for Member Training Report.'})

        fs = FileSystemStorage()
        member_file_path = fs.save(member_file.name, member_file)
        member_file_path = fs.path(member_file_path)

        try:
            df_member = pd.read_excel(member_file_path, engine='openpyxl', skiprows=9)
            df_member.columns = ['A', 'B', 'First_Name', 'D', 'Last_Name', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P']
            df_member = df_member[['First_Name', 'Last_Name']]
            name_counts = df_member.groupby(['First_Name', 'Last_Name']).size().reset_index(name='Count')
            request.session['member_data'] = name_counts.to_dict('records')
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Failed to read the Member file: {str(e)}'})

        # Save and process the Palms Report file
        if not palms_file.name.endswith('.xlsx'):
            return JsonResponse({'status': 'error', 'message': 'Please upload a valid .xlsx file for Palms Report.'})

        palms_file_path = fs.save(palms_file.name, palms_file)
        palms_file_path = fs.path(palms_file_path)

        try:
            df_palms = pd.read_excel(palms_file_path, engine='openpyxl', header=7)
            expected_columns = [
                'First Name', 'Last Name', 'P', 'A', 'L', 'M', 'S', 'RGI', 'RGO', 'RRI', 'RRO', 'V', '1-2-1', 'TYFCB', 'CEU', 'T'
            ]
            df_palms = df_palms[expected_columns]
            df_palms.rename(columns={'First Name': 'First_Name', 'Last Name': 'Last_Name'}, inplace=True)
            member_data = request.session.get('member_data', [])
            member_df = pd.DataFrame(member_data)
            df_palms = df_palms.merge(member_df, how='left', on=['First_Name', 'Last_Name'])
            df_palms['Absent_Score'] = df_palms['A'].map({0: 15, 1: 10, 2: 5, 3: 0})
            df_palms['Late_Score'] = df_palms['L'].apply(lambda x: 5 if x == 0 else 0)
            df_palms['Referral_Score'] = df_palms.apply(lambda row: 
                20 if (row['RGO'] + row['RGI']) >= 32 else
                15 if (row['RGO'] + row['RGI']) >= 26 else
                10 if (row['RGO'] + row['RGI']) >= 20 else
                5 if (row['RGO'] + row['RGI']) >= 13 else 0,
                axis=1
            )
            df_palms['Visitor_Score'] = df_palms['V'].apply(lambda x: 
                20 if x >= 20 else
                15 if x >= 13 else
                10 if x >= 7 else
                5 if x >= 3 else 0
            )
            df_palms['TYFCB_Score'] = df_palms['TYFCB'].apply(lambda x: 
                15 if x >= 2000000 else
                10 if 1000000 <= x < 2000000 else
                5 if 500000 <= x < 1000000 else 0
            )
            df_palms['Testimonial_Score'] = df_palms['T'].apply(lambda x: 
                10 if x >= 2 else
                5 if x == 1 else 0
            )
            df_palms['training_Score'] = df_palms['Count'].apply(lambda x: 
                15 if x >= 3 else
                10 if x == 2 else
                5 if x == 1 else 0
            )
            df_palms['Total_Score'] = df_palms[['Absent_Score', 'Late_Score', 'Referral_Score', 'Visitor_Score', 'TYFCB_Score', 'Testimonial_Score', 'training_Score']].sum(axis=1)
            df_palms['Projected_Score'] = df_palms['Total_Score'].apply(lambda x:
                'Green' if x >= 70 else
                'Amber' if x >= 50 else
                'Red' if x >= 30 else 'Grey'
            )
            request.session['palms_data'] = df_palms.to_dict('records')
        except (EmptyDataError, ParserError):
            return JsonResponse({'status': 'error', 'message': 'The Palms file is not valid or is corrupted.'})
        except KeyError as e:
            return JsonResponse({'status': 'error', 'message': f'Column not found: {str(e)}'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Failed to read the Palms file: {str(e)}'})

        # Save chapter name in session
        request.session['chapter_name'] = chapter_name

        # Both files were successfully processed, redirect to the final data page
        return JsonResponse({
            'status': 'success',
            'message': 'Data Captured!',
            'redirect_url': reverse('final_data')
        })

    return render(request, 'upload_both_reports.html')
    

def final_data_view(request):
    # Retrieve data from session
    member_data = request.session.get('member_data', [])
    palms_data = request.session.get('palms_data', [])
    chapter_name = request.session.get('chapter_name', 'N/A')  # Retrieve chapter name

    total_referral_score = 0
    total_tyfcb_score = 0
    total_visitor_score = 0 

    for record in palms_data:
        # Combine RGI and RGO for Referral_Score
        rgi = record.get('RGI', 0)
        rgo = record.get('RGO', 0)
        referral_score = rgi + rgo
        visitor = record.get('V', 0)
        # record['Referral_Score'] = referral_score

        total_referral_score += referral_score
        total_tyfcb_score += record.get('TYFCB_Score', 0)
        total_visitor_score += record.get('V', 0)

        # Calculate tooltip for TYFCB_Score
        tyfcb = record.get('TYFCB', 0)
        if tyfcb >= 2000000:
            record['TYFCB_tooltip'] = "You are a star ⭐"
        elif 1000000 <= tyfcb < 2000000:
            record['TYFCB_tooltip'] = f"You need {2000000 - tyfcb} tyfcb value more to achieve 15 points."
        elif 500000 <= tyfcb < 1000000:
            record['TYFCB_tooltip'] = (
                f"You need {2000000 - tyfcb} tyfcb value more to achieve 15 points and "
                f"{1000000 - tyfcb} tyfcb value more to achieve 10 points."
            )
        else:
            record['TYFCB_tooltip'] = (
                f"You need {2000000 - tyfcb} tyfcb value more to achieve 15 points, "
                f"{1000000 - tyfcb} tyfcb value more to achieve 10 points, and "
                f"{500000 - tyfcb} tyfcb value more to achieve 5 points."
            )

        # Calculate tooltip for V score
        visitor = record.get('V', 0)
        if visitor >= 20:
            record['V_tooltip'] = "You are a star ⭐"
        elif 13 <= visitor < 20:
            record['V_tooltip'] = f"You need {20 - visitor} more to achieve 20 points."
        elif 7 <= visitor < 13:
            record['V_tooltip'] = (
                f"You need {20 - visitor} more to achieve 15 points and "
                f"{13 - visitor} more to achieve 10 points."
            )
        elif 3 <= visitor < 7:
            record['V_tooltip'] = (
                f"You need {20 - visitor} more to achieve 15 points, "
                f"{13 - visitor} more to achieve 10 points, and "
                f"{7 - visitor} more to achieve 5 points."
            )
        else:
            record['V_tooltip'] = (
                f"You need {20 - visitor} more to achieve 15 points, "
                f"{13 - visitor} more to achieve 10 points, "
                f"{7 - visitor} more to achieve 5 points, and "
                f"{3 - visitor} more to achieve 0 points."
            )


        # Calculate tooltip for combined Referral_Score
        if referral_score >= 32:
            record['Referral_tooltip'] = "You are a star ⭐"
        elif 26 <= referral_score < 32:
            record['Referral_tooltip'] = f"You need {32 - referral_score} referrals more to achieve 20 points."
        elif 20 <= referral_score < 26:
            record['Referral_tooltip'] = (
                f"You need {32 - referral_score} referrals more to achieve 20 points and "
                f"{26 - referral_score} referrals more to achieve 15 points."
            )
        elif 13 <= referral_score < 20:
            record['Referral_tooltip'] = (
                f"You need {32 - referral_score} referrals more to achieve 20 points, "
                f"{26 - referral_score} referrals more to achieve 15 points, and "
                f"{20 - referral_score} referrals more to achieve 10 points."
            )
        else:
            record['Referral_tooltip'] = (
                f"You need {32 - referral_score} referrals more to achieve 20 points, "
                f"{26 - referral_score} referrals more to achieve 15 points, "
                f"{20 - referral_score} referrals more to achieve 10 points, and "
                f"{13 - referral_score} referrals more to achieve 5 points."
            )

        # Add other tooltips
        highest_points = {
            'Absent_Score': 15,
            'Late_Score': 5,
            'Visitor_Score': 20,
            'Testimonial_Score': 10,
            'training_Score': 15
        }

        tooltip_data = {}
        for score_type, highest_point in highest_points.items():
            current_score = record.get(score_type, 0)
            remaining_points = highest_point - current_score

            if current_score == highest_point:
                tooltip_data[score_type] = "You are a star ⭐"
            else:
                tooltip_data[score_type] = f"You need {remaining_points} points to be a star"
        
        record['tooltip_data'] = tooltip_data

    # Pass the data to the template
    context = {
        'member_data': member_data,
        'palms_data': palms_data,
        'chapter_name': chapter_name,  # Include chapter name in context
        'total_referral_score': total_referral_score,  # Store total referral score
        'total_tyfcb_score': total_tyfcb_score,
    }

    return render(request, 'final_data.html', context)






def export_go_green_excel(request):
    # Retrieve data from session
    palms_data = request.session.get('palms_data', [])

    # Create a DataFrame from the session data
    df = pd.DataFrame(palms_data)

    # Calculate the Referral_Value as the sum of RGO and RGI
    df['Referral_Value'] = df['RGO'] + df['RGI']

    # Create the 'Name' field by combining 'First_Name' and 'Last_Name'
    df['Name'] = df['First_Name'] + ' ' + df['Last_Name']

    # Add a serial number (Sr No.) field
    df['Sr No.'] = df.reset_index().index + 1  # Assuming you want 1-based index

    # Rename columns as specified
    df.rename(columns={
        'A': 'Absent Value',
        'L': 'Late Value',
        'V': 'Visitor Value',
        'TYFCB': 'TYFCB Vale',
        'T': 'Testimonial Value',
        'Count': 'Training Value',
        'Absent_Score': 'Absents = Score',
        'Late_Score': 'Late = Score',
        'Referral_Score': 'Total Ref = Score',
        'Visitor_Score': 'Total Vis = Score',
        'TYFCB_Score': 'Total Amt = Score',
        'training_Score': 'Total Trngs = Score',
        'Testimonial_Score': 'Tot Testimonails = Score',
        'Total_Score': 'Total Score'
    }, inplace=True)

    # Define the fields to include in the export
    fields = [
        'Sr No.', 'Name', 'Absent Value', 'Late Value', 'Visitor Value', 'Referral_Value',
        'TYFCB Vale', 'Testimonial Value', 'Training Value', 'Absents = Score',
        'Late = Score', 'Total Ref = Score', 'Total Vis = Score',
        'Total Amt = Score', 'Total Trngs = Score', 'Tot Testimonails = Score', 'Total Score'
    ]

    # Filter the DataFrame to include only the specified fields
    df = df[fields]

    # Create a BytesIO buffer for the Excel file
    buffer = BytesIO()

    # Write the DataFrame to the buffer as an Excel file
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Go Green Data', index=False)
        workbook = writer.book
        worksheet = writer.sheets['Go Green Data']

        # Define the format for each condition
        green_format = workbook.add_format({'bg_color': '#00FF00'})  # Green
        amber_format = workbook.add_format({'bg_color': '#FFA500'})  # Amber (orange)
        red_format = workbook.add_format({'bg_color': '#FF0000'})    # Red
        grey_format = workbook.add_format({'bg_color': '#808080'})   # Grey

        # Apply conditional formatting based on the Total Score
        worksheet.conditional_format('Q2:Q{}'.format(len(df) + 1), {
            'type': 'cell',
            'criteria': '>=',
            'value': 70,
            'format': green_format
        })

        worksheet.conditional_format('Q2:Q{}'.format(len(df) + 1), {
            'type': 'cell',
            'criteria': 'between',
            'minimum': 50,
            'maximum': 69,
            'format': amber_format
        })

        worksheet.conditional_format('Q2:Q{}'.format(len(df) + 1), {
            'type': 'cell',
            'criteria': 'between',
            'minimum': 30,
            'maximum': 49,
            'format': red_format
        })

        worksheet.conditional_format('Q2:Q{}'.format(len(df) + 1), {
            'type': 'cell',
            'criteria': '<',
            'value': 30,
            'format': grey_format
        })

    # Rewind the buffer's position to the beginning
    buffer.seek(0)

    # Create the HttpResponse to send the file
    response = HttpResponse(buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=go_green_data.xlsx'

    return response