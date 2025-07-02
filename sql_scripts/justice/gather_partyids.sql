		-- People who are attached to Supervision Cases
		SELECT DISTINCT 
			 P.PartyID
			,TypeOfParty	='Supervision Defendant'
		INTO {{DB_NAME}}.DBO.PartiesToConvert
		FROM
			Justice.DBO.SupCaseHdr S
				INNER JOIN Justice.DBO.PARTY P WITH (NOLOCK) ON S.DefendantPartyID=P.PartyID
	UNION
		-- getting associates of supervision offenders			
		SELECT DISTINCT 
			 PHI.PartyID
			,TypeOfParty	='Supervision Defendant Associate'
		FROM
			Justice.DBO.SupCaseHdr S
				INNER JOIN Justice.DBO.PARTY PLO WITH (NOLOCK) ON S.DefendantPartyID=PLO.PartyID
				INNER JOIN Justice.DBO.xPartyPartyAssociate XPPA WITH (NOLOCK) ON PLO.PartyID=XPPA.PartyIDLow AND XPPA.Deleted=0
				INNER JOIN Justice.DBO.PARTY PHI WITH (NOLOCK) ON XPPA.PartyIDHigh=PHI.PartyID
	UNION
		-- getting reversed associates of supervision offenders			
		SELECT DISTINCT 
			 PHI.PartyID
			,TypeOfParty	='Supervision Defendant Associate'
		FROM
			Justice.DBO.SupCaseHdr S
				INNER JOIN Justice.DBO.PARTY PHI WITH (NOLOCK) ON S.DefendantPartyID=PHI.PartyID
				INNER JOIN Justice.DBO.xPartyPartyAssociate XPPA WITH (NOLOCK) ON PHI.PartyID=XPPA.PartyIDHigh AND XPPA.Deleted=0
				INNER JOIN Justice.DBO.PARTY PLO WITH (NOLOCK) ON XPPA.PartyIDLow=PLO.PartyID
	UNION
	 -- Victims into ind_Individual tables
		SELECT DISTINCT 
			 s.PartyID
			,TypeOfParty		='Victim'
		FROM
		   Justice.DBO.SupCaseHdr su 
				INNER JOIN Justice.DBO.CaseParty cp ON cp.CaseID = su.CaseID
				INNER JOIN Justice.DBO.CasePartyConn conn ON conn.CasePartyID = cp.CasePartyID AND conn.BaseConnKy = 'VI'
				INNER JOIN Justice.DBO.Party s ON cp.PartyID = s.PartyId
	UNION
	 -- All Attorneys for the Referral Screen (def & pros)
		SELECT DISTINCT 
			 s.PartyID
			,TypeOfParty		='Attorneys'
		FROM
			Justice.dbo.Atty s
				INNER JOIN Justice.DBO.Party p ON s.PartyID = p.PartyId
	UNION
	 -- Agency Officers, not supervision officers, those are in uSupOfficer
		SELECT DISTINCT 
			 s.PartyID
			,TypeOfParty		='Officers'
		FROM
		   Justice.DBO.Officer s 
				INNER JOIN Justice.DBO.Party p ON s.PartyID = p.PartyId
	UNION
	 -- Schnools (In case this is needed for Juvenile)
		SELECT DISTINCT 
			 s.PartyID
			,TypeOfParty		='Schools'
		FROM
		   Justice.DBO.School su 
				INNER JOIN Justice.DBO.Party s ON su.SchoolID=s.PartyID
	UNION
	-- 20250701 JR Added employers of supervised defendants
		SELECT DISTINCT
			 EMPL.PartyID
			,TypeOfParty	='Employer of a Supervised Defendant'
		FROM
			Justice.dbo.SupCaseHdr S
				INNER JOIN Justice.dbo.PartyEmployer PE ON S.DefendantPartyID=PE.PartyID
				INNER JOIN Justice.dbo.Party EMPL ON PE.EMPLOYERID=EMPL.PARTYID;

---------------------------------------------------------------------------------------------------
	ALTER TABLE {{DB_NAME}}.DBO.PartiesToConvert ALTER COLUMN PartyID INT NOT NULL;
	ALTER TABLE {{DB_NAME}}.DBO.PartiesToConvert ALTER COLUMN TypeOfParty VARCHAR(50) NOT NULL;
	ALTER TABLE {{DB_NAME}}.DBO.PartiesToConvert ADD CONSTRAINT PartyID PRIMARY KEY (PartyID,TypeOfParty);
---------------------------------------------------------------------------------------------------